MATCH 3 METHOD FREEZE v047

Copy all four files in this folder to project\tools\, then run:

& ".\.venv\Scripts\python.exe" ".\tools\upgrade_transient_automation_v047_match3_lessons.py"
& ".\.venv\Scripts\python.exe" -m automation.runner status
& ".\.venv\Scripts\python.exe" -m automation.runner run-next
& ".\.venv\Scripts\python.exe" -m automation.runner verify-stage --stage order11_match3_method_freeze_v047

The installer makes no network calls, reads no pixels, does not rerun the detector,
and does not alter candidate state. The registered stage only reads completed Match-3
reports and writes a method-freeze artifact.
