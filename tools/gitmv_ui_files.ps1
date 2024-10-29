# 移動元と移動先のパスを定義
# カレントディレクトリで実効すること
$source_dir = "src/genai_tag_db_tools/gui/widgets"
$dest_dir = "src/genai_tag_db_tools/gui/designer"

# .uiファイルと_ui.pyファイルを取得して移動
Get-ChildItem -Path $source_dir |
    Where-Object {
        $_.Name -match '\.(ui|_ui\.py)$' -and
        $_.Name -notmatch '^main_window'
    } |
    ForEach-Object {
        git mv "$source_dir/$($_.Name)" "$dest_dir/$($_.Name)"
        Write-Host "Moved $($_.Name) to designer directory"
    }

# ウィンドウは個別にコマンドで処理
# git mv "src\genai_tag_db_tools\gui\widgets\main_window_ui.py" "src\genai_tag_db_tools\gui\designer\main_window.ui"
# git mv "src\genai_tag_db_tools\gui\widgets\main_window_ui.py" "src\genai_tag_db_tools\gui\designer\main_window_ui.py"