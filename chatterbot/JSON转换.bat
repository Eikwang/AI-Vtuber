@echo off

SET CONDA_PATH=..\Miniconda3

REM ����base����
CALL %CONDA_PATH%\Scripts\activate.bat %CONDA_PATH%

SET KMP_DUPLICATE_LIB_OK=TRUE

echo ==============================================
echo        ���� TXT ת JSON ת������
echo ==============================================
echo.

python T2J.py

echo.
echo ==============================================
echo ת����ɣ����������������������֤�����
echo ==============================================
echo.

pause