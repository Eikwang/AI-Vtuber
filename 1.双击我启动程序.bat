@echo off

SET CONDA_PATH=.\Miniconda3

REM ����base����
CALL %CONDA_PATH%\Scripts\activate.bat %CONDA_PATH%

SET KMP_DUPLICATE_LIB_OK=TRUE

python webui.py

cmd /k