@echo off

SET CONDA_PATH=..\Miniconda3

REM ����base����
CALL %CONDA_PATH%\Scripts\activate.bat %CONDA_PATH%

SET KMP_DUPLICATE_LIB_OK=TRUE

echo ==============================================
echo           ChatterBot �����������
echo ==============================================
echo.

python data_quality_checker.py

echo.
echo ==============================================
echo �������������ɣ�
echo ����ݱ��潨���Ż����ݺ��ٽ���ѵ����
echo ==============================================
echo.

pause