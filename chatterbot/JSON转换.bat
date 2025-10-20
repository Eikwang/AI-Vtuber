@echo off

SET CONDA_PATH=..\Miniconda3

REM 激活base环境
CALL %CONDA_PATH%\Scripts\activate.bat %CONDA_PATH%

SET KMP_DUPLICATE_LIB_OK=TRUE

echo ==============================================
echo        智能 TXT 转 JSON 转换工具
echo ==============================================
echo.

python T2J.py

echo.
echo ==============================================
echo 转换完成！请运行数据质量检查来验证结果。
echo ==============================================
echo.

pause