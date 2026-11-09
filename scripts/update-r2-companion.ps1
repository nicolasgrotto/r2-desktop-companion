param(
    [string]$InstallDirectory = '',
    [string]$DataDirectory = '',
    [int]$ExpectedProcessId = 0,
    [long]$ProcessStarted = 0,
    [switch]$CheckOnly,
    [switch]$Yes,
    [switch]$NoRestart,
    [switch]$Console
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:LogFile = $null
$script:AssetName = 'R2Companion-Windows-x64.zip'

function Write-R2Log([string]$Message) {
    $line = '{0} {1}' -f [DateTime]::Now.ToString('s'), $Message
    if ($script:LogFile) { Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8 }
    Write-Host $line
}

function Show-R2Message([string]$Message, [switch]$Question) {
    if ($Console) {
        Write-Host $Message
        if ($Question) { return $false }
        return
    }
    Add-Type -AssemblyName System.Windows.Forms
    $buttons = if ($Question) { [System.Windows.Forms.MessageBoxButtons]::YesNo } else { [System.Windows.Forms.MessageBoxButtons]::OK }
    $result = [System.Windows.Forms.MessageBox]::Show($Message, 'R2 Companion - Atualizacoes', $buttons)
    if ($Question) { return $result -eq [System.Windows.Forms.DialogResult]::Yes }
}

function Convert-R2Version([string]$Value) {
    if ($Value -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
        throw 'Versao estavel invalida. Use X.Y.Z.'
    }
    return [version]$Value
}

function Get-R2FullPath([string]$Path) {
    if (-not $Path -or -not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\')) {
        throw 'Use um caminho local absoluto.'
    }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    if ($full -eq [IO.Path]::GetPathRoot($full).TrimEnd('\', '/') -or $full.Length -lt 4) {
        throw 'Diretorio raiz nao pode ser utilizado.'
    }
    return $full
}

function Test-R2Within([string]$Path, [string]$Root) {
    return $Path.StartsWith($Root.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-R2NoLinks([string]$Path, [switch]$Recurse) {
    $current = [IO.DirectoryInfo]::new($Path)
    while ($current) {
        if ($current.Exists -and ($current.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Links e pontos de redirecionamento nao sao permitidos.'
        }
        $current = $current.Parent
    }
    if ($Recurse -and (Test-Path -LiteralPath $Path)) {
        foreach ($item in Get-ChildItem -LiteralPath $Path -Force -Recurse) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'A instalacao contem links; atualizacao cancelada.'
            }
        }
    }
}

function Read-R2Release([string]$Directory) {
    $path = Join-Path $Directory 'release.json'
    if ((Get-Item -LiteralPath $path).Length -gt 4096) { throw 'Metadata muito grande.' }
    $data = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($data.schema_version -ne 1 -or $data.repository -cnotmatch '^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+$') {
        throw 'Metadata de instalacao invalida.'
    }
    $null = Convert-R2Version $data.version
    return $data
}

function Get-R2LatestRelease([string]$Repository) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    return Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/latest" -Headers @{
        'User-Agent' = 'R2Companion-Updater'
        'Accept' = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
    } -TimeoutSec 30
}

function Get-R2Asset($Release, [string]$Repository, [string]$Name) {
    $assets = @($Release.assets | Where-Object { $_.name -ceq $Name })
    if ($assets.Count -ne 1) { throw "Asset ausente ou duplicado: $Name" }
    $asset = $assets[0]
    $expected = "https://github.com/$Repository/releases/download/$($Release.tag_name)/$Name"
    if ($asset.browser_download_url -cne $expected -or $asset.size -le 0 -or $asset.size -gt 536870912) {
        throw 'Origem ou tamanho do download invalido.'
    }
    return $asset
}

function Get-R2Download([string]$Url, [string]$Destination) {
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -TimeoutSec 180 -Headers @{
        'User-Agent' = 'R2Companion-Updater'
    }
}

function Test-R2Checksum([string]$Archive, [string]$Checksum) {
    if ((Get-Item -LiteralPath $Checksum).Length -gt 1024) { throw 'Checksum invalido.' }
    $contents = (Get-Content -LiteralPath $Checksum -Raw -Encoding UTF8).Trim()
    if ($contents -cnotmatch '^([a-fA-F0-9]{64})\s+\*?R2Companion-Windows-x64\.zip$') {
        throw 'Formato de checksum invalido.'
    }
    $expected = $Matches[1]
    if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ine $expected) {
        throw 'SHA-256 incorreto. A instalacao anterior foi preservada.'
    }
}

function Expand-R2Package([string]$Archive, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $root = Get-R2FullPath $Destination
    if (Test-Path -LiteralPath $root) { throw 'A pasta de extracao ja existe.' }
    Assert-R2NoLinks ([IO.Path]::GetDirectoryName($root))
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -eq 0 -or $zip.Entries.Count -gt 10000) { throw 'Quantidade de arquivos invalida.' }
        $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $total = [long]0
        $plan = @()
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            $parts = $name.TrimEnd('/').Split('/')
            if ($parts.Count -lt 1 -or $parts[0] -cne 'R2Companion' -or $name.Contains('\')) {
                throw 'Raiz do pacote invalida.'
            }
            foreach ($part in $parts) {
                if (-not $part -or $part -in @('.', '..') -or $part -match '[<>:"|?*\x00-\x1f]' -or
                    $part.EndsWith('.') -or $part.EndsWith(' ') -or
                    $part -match '^(?i:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[0-9\u00b9\u00b2\u00b3]|LPT[0-9\u00b9\u00b2\u00b3])(?:\.|$)') {
                    throw 'Nome inseguro no ZIP.'
                }
            }
            $kind = ($entry.ExternalAttributes -shr 16) -band 61440
            if ($kind -notin @(0, 32768, 16384) -or ($entry.ExternalAttributes -band 1024)) {
                throw 'Links e arquivos especiais nao sao permitidos no ZIP.'
            }
            $target = [IO.Path]::GetFullPath((Join-Path $root ($parts -join [IO.Path]::DirectorySeparatorChar)))
            if (-not (Test-R2Within $target $root) -or -not $names.Add($target)) {
                throw 'Caminho externo ou duplicado no ZIP.'
            }
            $total += $entry.Length
            if ($entry.Length -gt 536870912 -or $total -gt 1073741824) { throw 'ZIP excede limite de tamanho.' }
            $plan += [pscustomobject]@{ Entry = $entry; Target = $target; Directory = $name.EndsWith('/') }
        }
        $null = New-Item -Path $root -ItemType Directory
        foreach ($item in $plan) {
            if ($item.Directory) {
                $null = [IO.Directory]::CreateDirectory($item.Target)
            } else {
                $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($item.Target))
                $inputStream = $item.Entry.Open()
                try {
                    $outputStream = [IO.File]::Open($item.Target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
                    try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
                } finally { $inputStream.Dispose() }
            }
        }
    } finally { $zip.Dispose() }
    return Join-Path $root 'R2Companion'
}

function Assert-R2Package([string]$Directory, [string]$Repository, [string]$Version) {
    $metadata = Read-R2Release $Directory
    if ($metadata.repository -cne $Repository -or $metadata.version -cne $Version) {
        throw 'O pacote nao corresponde a release solicitada.'
    }
    foreach ($file in @('R2Companion.exe', '_internal\PySide6\Qt6Core.dll',
                         '_internal\PySide6\Qt6Multimedia.dll',
                         '_internal\r2_companion\assets\characters\default\manifest.json',
                         '_internal\scripts\update-r2-companion.ps1')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Directory $file) -PathType Leaf)) {
            throw "Pacote incompleto: $file"
        }
    }
    Assert-R2NoLinks $Directory -Recurse
}

function Stop-R2Installation([string]$Directory, [int]$RequestedId = 0, [long]$Started = 0) {
    $expectedPath = Join-Path $Directory 'R2Companion.exe'
    $processes = @(Get-Process -Name R2Companion -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -ieq $expectedPath } catch { $false }
    })
    if ($RequestedId) {
        $requested = Get-Process -Id $RequestedId -ErrorAction SilentlyContinue
        if ($requested) {
            $epoch = [DateTime]::new(1970, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)
            $actualStarted = [long][Math]::Floor(($requested.StartTime.ToUniversalTime() - $epoch).TotalSeconds)
            if ($requested.Path -ine $expectedPath -or [Math]::Abs($actualStarted - $Started) -gt 1) {
                throw 'O processo informado nao corresponde a instalacao.'
            }
        }
    }
    if ($processes.Count -eq 0) { return }
    if (-not ('R2WindowCloser' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class R2WindowCloser {
    public delegate bool Callback(IntPtr hwnd, IntPtr parameter);
    [DllImport("user32.dll")] static extern bool EnumWindows(Callback callback, IntPtr parameter);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint process);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr w, IntPtr l);
    public static void Close(uint process) {
        EnumWindows((hwnd, parameter) => {
            uint owner;
            GetWindowThreadProcessId(hwnd, out owner);
            if (owner == process) PostMessage(hwnd, 0x0010, IntPtr.Zero, IntPtr.Zero);
            return true;
        }, IntPtr.Zero);
    }
}
'@
    }
    foreach ($process in $processes) {
        Write-R2Log "Solicitando encerramento do R2 PID $($process.Id)."
        [R2WindowCloser]::Close($process.Id)
        if (-not $process.WaitForExit(15000)) { throw 'O R2 nao encerrou. Feche pelo menu Sair e tente novamente.' }
    }
}

function Start-R2Installation([string]$Directory, [string]$UserData = '') {
    $arguments = @()
    if ($UserData) {
        if ($UserData.Contains('"')) { throw 'Diretorio de dados invalido.' }
        $arguments = @('--data-dir', ('"{0}"' -f $UserData.TrimEnd('\')))
    }
    $options = @{ FilePath = (Join-Path $Directory 'R2Companion.exe'); WorkingDirectory = $Directory;
                  WindowStyle = 'Hidden'; PassThru = $true }
    if ($arguments.Count) { $options.ArgumentList = $arguments }
    $process = Start-Process @options
    if ($process.WaitForExit(3000)) { throw "O aplicativo encerrou durante a inicializacao (codigo $($process.ExitCode))." }
}

function Wait-R2FileAccess {
    Start-Sleep -Milliseconds 500
}

function Move-R2Directory([string]$Source, [string]$Destination) {
    $sourcePath = Get-R2FullPath $Source
    $destinationPath = Get-R2FullPath $Destination
    Assert-R2NoLinks $sourcePath -Recurse
    Assert-R2NoLinks ([IO.Path]::GetDirectoryName($destinationPath))
    for ($attempt = 1; $attempt -le 16; $attempt++) {
        try {
            Move-Item -LiteralPath $sourcePath -Destination $destinationPath
            return
        } catch [IO.IOException], [UnauthorizedAccessException] {
            if ($attempt -eq 16) { throw }
            Write-R2Log "Aguardando liberacao de arquivos pelo Windows, tentativa $attempt de 16."
            Wait-R2FileAccess
        }
    }
}

function Install-R2Package([string]$Directory, [string]$Package, [string]$Repository,
                           [string]$Version, [string]$UserData = '', [switch]$Restart) {
    $install = Get-R2FullPath $Directory
    $packagePath = Get-R2FullPath $Package
    Assert-R2NoLinks $install -Recurse
    Assert-R2Package $packagePath $Repository $Version
    $parent = [IO.Path]::GetDirectoryName($install)
    if ([IO.Path]::GetPathRoot($install) -ine [IO.Path]::GetPathRoot($packagePath)) {
        throw 'Staging e instalacao devem estar no mesmo volume.'
    }
    if (Test-R2Within $packagePath $install) { throw 'Staging nao pode ficar dentro da instalacao.' }
    $backup = $install + '.backup-' + [Guid]::NewGuid().ToString('N')
    $failed = $install + '.failed-' + [Guid]::NewGuid().ToString('N')
    $null = Get-R2FullPath $backup
    $null = Get-R2FullPath $failed
    Set-Location -LiteralPath $parent
    $movedOld = $false
    $movedNew = $false
    try {
        Move-R2Directory $install $backup
        $movedOld = $true
        Move-R2Directory $packagePath $install
        $movedNew = $true
        Assert-R2Package $install $Repository $Version
        if ($Restart) { Start-R2Installation $install $UserData }
        Write-R2Log "Atualizado para $Version. Backup: $backup"
        return $backup
    } catch {
        $failure = $_
        if ($movedNew -and (Test-Path -LiteralPath $install)) {
            Stop-R2Installation $install
            Move-R2Directory $install $failed
        }
        if ($movedOld) { Move-R2Directory $backup $install }
        if ($Restart -and $movedOld) {
            try { Start-R2Installation $install $UserData } catch { Write-R2Log 'Nao foi possivel reiniciar a versao recuperada.' }
        }
        throw "Atualizacao falhou; recuperacao solicitada. $failure"
    }
}

function Invoke-R2Update {
    $install = Get-R2FullPath $InstallDirectory
    Assert-R2NoLinks $install -Recurse
    $metadata = Read-R2Release $install
    $current = Convert-R2Version $metadata.version
    $data = if ($DataDirectory) { Get-R2FullPath $DataDirectory } else {
        Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'R2DesktopCompanion\R2Companion'
    }
    if ($data -ieq $install -or (Test-R2Within $data $install)) { throw 'Dados devem ficar fora da instalacao.' }
    $logs = Join-Path $data 'updates'
    $null = New-Item -Path $logs -ItemType Directory -Force
    $script:LogFile = Join-Path $logs 'update.log'
    $lock = $null
    $stage = $null
    try {
        $lock = [IO.File]::Open(($install + '.update.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        Write-R2Log "Verificando $($metadata.repository), versao $current."
        $release = Get-R2LatestRelease $metadata.repository
        if ($release.draft -or $release.prerelease -or $release.tag_name -cnotmatch '^v(.+)$') {
            throw 'A resposta nao identifica uma release estavel.'
        }
        $version = $Matches[1]
        $latest = Convert-R2Version $version
        if ($latest -le $current) {
            Write-R2Log 'Nenhuma atualizacao disponivel.'
            Show-R2Message "O R2 esta atualizado ($current)."
            return
        }
        $zipAsset = Get-R2Asset $release $metadata.repository $script:AssetName
        $hashAsset = Get-R2Asset $release $metadata.repository ($script:AssetName + '.sha256')
        if ($CheckOnly) {
            Show-R2Message "Versao $version disponivel. Execute novamente sem -CheckOnly para instalar."
            return
        }
        if (-not $Yes -and -not (Show-R2Message "Versao $version disponivel. Baixar e instalar? O R2 sera encerrado apos a validacao e reiniciado ao concluir." -Question)) {
            Write-R2Log 'Instalacao cancelada pelo usuario.'
            return
        }
        $parent = [IO.Path]::GetDirectoryName($install)
        $stage = Join-Path $parent ('.r2-update-' + [Guid]::NewGuid().ToString('N'))
        $null = Get-R2FullPath $stage
        $null = New-Item -Path $stage -ItemType Directory
        $zip = Join-Path $stage $script:AssetName
        $hash = $zip + '.sha256'
        Write-R2Log 'Baixando pacote e checksum.'
        Get-R2Download $zipAsset.browser_download_url $zip
        Get-R2Download $hashAsset.browser_download_url $hash
        if ((Get-Item -LiteralPath $zip).Length -ne $zipAsset.size) { throw 'Tamanho do download incorreto.' }
        Test-R2Checksum $zip $hash
        $package = Expand-R2Package $zip (Join-Path $stage 'extracted')
        Assert-R2Package $package $metadata.repository $version
        Stop-R2Installation $install $ExpectedProcessId $ProcessStarted
        $backup = Install-R2Package $install $package $metadata.repository $version $data -Restart:(-not $NoRestart)
        Show-R2Message "R2 atualizado para $version. Backup preservado em $backup."
    } finally {
        if ($lock) { $lock.Dispose() }
        if ($stage -and (Test-Path -LiteralPath $stage)) {
            $validated = Get-R2FullPath $stage
            $parent = [IO.Path]::GetDirectoryName($install)
            if ((Test-R2Within $validated $parent) -and ([IO.Path]::GetFileName($validated) -match '^\.r2-update-[a-f0-9]{32}$')) {
                Assert-R2NoLinks $validated -Recurse
                Remove-Item -LiteralPath $validated -Recurse -Force
            }
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        if (-not $InstallDirectory) {
            $candidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
            if ([IO.Path]::GetFileName($candidate) -eq '_internal') { $candidate = [IO.Path]::GetDirectoryName($candidate) }
            $InstallDirectory = $candidate
        }
        Invoke-R2Update
        exit 0
    } catch {
        $message = "Nao foi possivel atualizar: $($_.Exception.Message)"
        try { Write-R2Log $message } catch { Write-Host $message }
        Show-R2Message $message
        exit 1
    }
}
