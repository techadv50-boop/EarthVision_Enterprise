@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  DOI -^> ReDIF Converter
echo ============================================
echo.
echo Starting the program...
echo If Windows SmartScreen appears:
echo   click More info  -^>  Run anyway
echo.

if exist "DOI_REDIF_Converter.exe" (
  start "" "DOI_REDIF_Converter.exe"
  echo Launched DOI_REDIF_Converter.exe
  echo A small control window should appear.
  echo If nothing opens, check DOI_REDIF_Converter.log in this folder.
  echo.
  pause
  exit /b 0
)

echo ERROR: DOI_REDIF_Converter.exe not found in this folder.
echo Unzip the download fully first, then run this file again.
echo.
pause
exit /b 1
