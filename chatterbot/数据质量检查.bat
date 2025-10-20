@echo off

SET CONDA_PATH=..\Miniconda3

REM 激活base环境
CALL %CONDA_PATH%\Scripts\activate.bat %CONDA_PATH%

SET KMP_DUPLICATE_LIB_OK=TRUE

echo ==============================================
echo           ChatterBot 数据质量检查
echo ==============================================
echo.

python data_quality_checker.py

echo.
echo ==============================================
echo 数据质量检查完成！
echo 请根据报告建议优化数据后再进行训练。
echo ==============================================
echo.

pause