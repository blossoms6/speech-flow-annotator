param(
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$OutputFile,
    [Parameter(Mandatory = $true)][string]$MetadataFile,
    [string]$Culture = "en-US"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
if ([string]::IsNullOrWhiteSpace($text)) {
    throw "The text is empty."
}

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $enabled = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled })
    $selected = $enabled | Where-Object { $_.VoiceInfo.Culture.Name -eq $Culture } | Select-Object -First 1
    if (-not $selected) {
        $selected = $enabled | Where-Object { $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq "en" } | Select-Object -First 1
    }
    if ($selected) {
        $synth.SelectVoice($selected.VoiceInfo.Name)
    }
    $synth.Rate = 0
    $synth.Volume = 100
    $synth.SetOutputToWaveFile($OutputFile)
    $synth.Speak($text)
    $synth.SetOutputToNull()

    $voice = $synth.Voice
    [pscustomobject]@{
        voice = $voice.Name
        culture = $voice.Culture.Name
        rate = $synth.Rate
        engine = "Windows System.Speech"
    } | ConvertTo-Json | Set-Content -LiteralPath $MetadataFile -Encoding UTF8
}
finally {
    $synth.Dispose()
}
