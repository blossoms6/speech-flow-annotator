const $ = (selector) => document.querySelector(selector);
const adminState = {user: null};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN", {hour12: false});
}

function showToast(message, kind = "success") {
  const toast = $("#adminToast");
  toast.textContent = message;
  toast.className = `admin-toast ${kind}`;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { toast.hidden = true; }, 4200);
}

async function adminFetch(url, options) {
  const response = await fetch(url, options);
  if (response.status === 401) { location.replace(`/login?next=${encodeURIComponent('/admin')}`); throw new Error("需要管理员登录。"); }
  if (response.status === 403) { location.replace("/"); throw new Error("没有管理员权限。"); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "管理操作失败。");
  return data;
}

async function loadOverview() {
  const data = await adminFetch("/api/admin/overview");
  adminState.user = data.admin;
  $("#adminIdentity").textContent = data.admin.username;
  $("#statUsers").textContent = data.users.total;
  $("#statActiveUsers").textContent = `${data.users.active} 个启用账户`;
  $("#statJobs").textContent = data.jobs.total;
  $("#statGuestJobs").textContent = `${data.jobs.guest} 个游客任务`;
  $("#statProcessing").textContent = data.jobs.counts.queued + data.jobs.counts.processing;
  $("#statFailed").textContent = data.jobs.counts.failed;
  $("#statStorage").textContent = formatBytes(data.storage.jobs_bytes);
  $("#statDiskFree").textContent = `磁盘剩余 ${formatBytes(data.storage.disk_free_bytes)}`;
  $("#statSessions").textContent = data.users.sessions;
  $("#statAdmins").textContent = `${data.users.admins} 位管理员`;
  const service = data.service;
  $("#serviceFacts").innerHTML = [
    ["版本", service.version],
    ["自动转写", service.transcription_available ? "可用" : "未安装"],
    ["离线声音", service.local_tts_available ? "可用" : "当前系统不可用"],
    ["默认模型", service.default_model],
    ["任务线程", service.worker_count],
    ["上传上限", `${service.max_upload_mb} MB`],
    ["音频时长", `${Math.round(service.max_duration_seconds / 60)} 分钟`],
  ].map(([label, value]) => `<div><dt>${label}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
}

async function loadUsers() {
  const query = encodeURIComponent($("#userQuery").value.trim());
  const data = await adminFetch(`/api/admin/users?query=${query}`);
  $("#userRows").innerHTML = data.items.length ? data.items.map(user => {
    const isSelf = user.id === adminState.user?.id;
    return `<tr>
      <td><b>${escapeHtml(user.username)}</b><small>${user.is_admin ? "管理员" : "普通用户"}</small></td>
      <td><span class="status-pill ${user.is_active ? "active" : "disabled"}">${user.is_active ? "启用" : "停用"}</span></td>
      <td>${user.session_count}</td><td>${formatDate(user.created_at)}</td>
      <td class="table-actions">
        <button data-user-id="${user.id}" data-user-action="active" data-value="${!user.is_active}" ${isSelf ? "disabled" : ""}>${user.is_active ? "停用" : "启用"}</button>
        <button data-user-id="${user.id}" data-user-action="admin" data-value="${!user.is_admin}" ${isSelf ? "disabled" : ""}>${user.is_admin ? "取消管理" : "设为管理"}</button>
      </td></tr>`;
  }).join("") : '<tr><td colspan="5" class="empty-row">没有匹配用户</td></tr>';
  document.querySelectorAll("[data-user-action]").forEach(button => button.onclick = updateUser);
}

async function updateUser(event) {
  const button = event.currentTarget;
  const action = button.dataset.userAction;
  const value = button.dataset.value === "true";
  const label = action === "active" ? (value ? "启用该用户" : "停用该用户") : (value ? "授予管理员权限" : "移除管理员权限");
  if (!window.confirm(`确定要${label}吗？`)) return;
  button.disabled = true;
  try {
    await adminFetch(`/api/admin/users/${button.dataset.userId}`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({[action === "active" ? "is_active" : "is_admin"]: value})});
    showToast(`${label}成功。`);
    await Promise.all([loadOverview(), loadUsers()]);
  } catch (reason) { showToast(reason.message, "error"); button.disabled = false; }
}

function statusLabel(status) {
  return ({queued: "排队", processing: "处理中", completed: "已完成", failed: "失败"})[status] || status;
}

async function loadJobs() {
  const params = new URLSearchParams({query: $("#jobQuery").value.trim(), status: $("#jobStatus").value, owner_type: $("#jobOwner").value});
  const data = await adminFetch(`/api/admin/jobs?${params}`);
  $("#jobRows").innerHTML = data.items.length ? data.items.map(job => `<tr>
    <td><b>${escapeHtml(job.original_name || job.id)}</b><small>${escapeHtml(job.id)} · ${job.input_mode === "text" ? "文稿" : "音频"}</small>${job.error ? `<em>${escapeHtml(job.error)}</em>` : ""}</td>
    <td>${escapeHtml(job.owner_name)}</td>
    <td><span class="status-pill ${job.status}">${statusLabel(job.status)}</span><small>${job.progress || 0}% · ${escapeHtml(job.stage || "")}</small></td>
    <td>${formatBytes(job.size_bytes)}</td><td>${formatDate(job.created_at)}</td>
    <td class="table-actions"><button class="delete-job" data-job-id="${job.id}" ${["queued", "processing"].includes(job.status) ? "disabled" : ""}>删除</button></td>
  </tr>`).join("") : '<tr><td colspan="6" class="empty-row">没有匹配任务</td></tr>';
  document.querySelectorAll(".delete-job").forEach(button => button.onclick = deleteJob);
}

async function deleteJob(event) {
  const button = event.currentTarget;
  if (!window.confirm("确定删除这个任务及其音频、结果和导出文件吗？此操作不能撤销。")) return;
  button.disabled = true;
  try {
    await adminFetch(`/api/admin/jobs/${button.dataset.jobId}`, {method: "DELETE"});
    showToast("任务已删除。");
    await Promise.all([loadOverview(), loadJobs()]);
  } catch (reason) { showToast(reason.message, "error"); button.disabled = false; }
}

async function cleanupGuests() {
  const days = Number($("#cleanupDays").value);
  if (!Number.isInteger(days) || days < 1 || days > 3650) { showToast("保留天数必须在 1–3650 之间。", "error"); return; }
  if (!window.confirm(`确定删除超过 ${days} 天且已经结束的游客任务吗？`)) return;
  $("#cleanupButton").disabled = true;
  try {
    const data = await adminFetch("/api/admin/cleanup", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({guest_older_than_days: days})});
    showToast(`清理完成，共删除 ${data.deleted_count} 个游客任务。`);
    await Promise.all([loadOverview(), loadJobs()]);
  } catch (reason) { showToast(reason.message, "error"); }
  finally { $("#cleanupButton").disabled = false; }
}

async function refreshAll() {
  $("#refreshAdmin").disabled = true;
  try { await Promise.all([loadOverview(), loadUsers(), loadJobs()]); }
  catch (reason) { showToast(reason.message, "error"); }
  finally { $("#refreshAdmin").disabled = false; }
}

$("#refreshAdmin").onclick = refreshAll;
$("#userSearch").onsubmit = event => { event.preventDefault(); loadUsers().catch(reason => showToast(reason.message, "error")); };
$("#jobFilter").onsubmit = event => { event.preventDefault(); loadJobs().catch(reason => showToast(reason.message, "error")); };
$("#cleanupButton").onclick = cleanupGuests;
$("#adminLogout").onclick = async () => { await fetch("/api/auth/logout", {method: "POST"}); location.replace("/login"); };
refreshAll();
