@echo off

SET CONDA_PATH=D:\AI\AI-Vtuber\Miniconda3

REM 激活base环境
CALL %CONDA_PATH%\Scripts\activate.bat %CONDA_PATH%

SET KMP_DUPLICATE_LIB_OK=TRUE

cd /d d:\AI\AI-Vtuber\DanmakuListener

python app.py

cmd /k