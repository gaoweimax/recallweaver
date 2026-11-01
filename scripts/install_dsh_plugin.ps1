$ErrorActionPreference = "Stop"

$defaultDshCmd = "C:\Users\$env:USERNAME\AppData\Local\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd"
$pluginPath = [System.IO.Path]::GetFullPath(
    (Join-Path (Split-Path -Parent $PSScriptRoot) "dsh-plugin-recallweaver")
)
$exitCode = 1

try {
    if (-not (Test-Path -LiteralPath $pluginPath -PathType Container)) {
        throw "找不到插件目录：$pluginPath"
    }

    $dshCmd = $defaultDshCmd
    if (-not (Test-Path -LiteralPath $dshCmd -PathType Leaf)) {
        Write-Host "未在默认位置找到 DSH 命令：$defaultDshCmd"
        $installPath = (Read-Host "请输入 DSH 安装目录或 dsh.cmd 的完整路径").Trim('"')

        if (Test-Path -LiteralPath $installPath -PathType Container) {
            $dshCmd = Join-Path $installPath "resources\runtime\cli\bin\dsh.cmd"
        }
        else {
            $dshCmd = $installPath
        }
    }

    if (-not (Test-Path -LiteralPath $dshCmd -PathType Leaf)) {
        throw "找不到 dsh.cmd：$dshCmd"
    }

    $dshCmd = [System.IO.Path]::GetFullPath($dshCmd)
    Write-Host "DSH 命令：$dshCmd"
    Write-Host "插件目录：$pluginPath"
    Write-Host "正在安装插件..."

    $output = & $dshCmd plugin --profile desktop add $pluginPath 2>&1
    $exitCode = $LASTEXITCODE
    foreach ($line in $output) {
        Write-Host $line
    }

    if ($exitCode -eq 0) {
        Write-Host "插件安装命令已成功完成。"
    }
    else {
        Write-Host "插件安装命令失败，退出代码：$exitCode"
    }
}
catch {
    Write-Host "安装失败：$($_.Exception.Message)"
}
finally {
    Write-Host "请彻底退出 DSH 托盘程序，重新打开以生效。"
    [void](Read-Host "按 Enter 键退出")
}

exit $exitCode
