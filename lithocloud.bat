@echo off
rem Launch LithoCloud. Run from an Anaconda Prompt with the
rem "rockslope" env active:  conda activate rockslope
cd /d %~dp0
set PYTHONPATH=%~dp0app;%PYTHONPATH%
python -m lithocloud %*
