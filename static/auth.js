const $ = (selector) => document.querySelector(selector);
let authMode = "login";

function safeNextPath() {
  const candidate = new URLSearchParams(location.search).get("next");
  return candidate && candidate.startsWith("/") && !candidate.startsWith("//") ? candidate : "/";
}

function setAuthMode(mode) {
  authMode = mode;
  const registering = mode === "register";
  document.querySelectorAll("[data-auth-mode]").forEach(button => {
    const active = button.dataset.authMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#authTitle").textContent = registering ? "创建本机账户" : "欢迎回来";
  $("#authIntro").textContent = registering
    ? "注册后即可进入工作台；你的任务将与此账户绑定。"
    : "登录后进入你的英语语流练习空间。";
  $("#authConfirmRow").hidden = !registering;
  $("#authConfirm").required = registering;
  $("#authPassword").autocomplete = registering ? "new-password" : "current-password";
  $("#authSubmit span:first-child").textContent = registering ? "注册并进入" : "登录并进入";
  $("#authError").hidden = true;
}

async function submitAuth(event) {
  event.preventDefault();
  const username = $("#authUsername").value.trim();
  const password = $("#authPassword").value;
  const error = $("#authError");
  if (authMode === "register" && password !== $("#authConfirm").value) {
    error.textContent = "两次输入的密码不一致。";
    error.hidden = false;
    return;
  }
  error.hidden = true;
  $("#authSubmit").disabled = true;
  try {
    const response = await fetch(`/api/auth/${authMode}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username, password}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "操作失败，请稍后重试。");
    location.replace(safeNextPath());
  } catch (reason) {
    error.textContent = reason.message;
    error.hidden = false;
    $("#authSubmit").disabled = false;
  }
}

async function boot() {
  const nextPath = safeNextPath();
  $("#guestAccess").href = nextPath === "/admin" ? "/" : nextPath;
  try {
    const response = await fetch("/api/auth/me", {cache: "no-store"});
    const data = await response.json();
    if (data.authenticated) {
      location.replace(safeNextPath());
      return;
    }
  } catch {
    const error = $("#authError");
    error.textContent = "无法连接本地服务，请确认软件仍在运行。";
    error.hidden = false;
  }
  document.querySelectorAll("[data-auth-mode]").forEach(button => {
    button.onclick = () => setAuthMode(button.dataset.authMode);
  });
  $("#authForm").addEventListener("submit", submitAuth);
}

boot();
