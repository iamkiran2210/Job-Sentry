Stand-in for the parts of YOUR repo that Phase 3 touches, rebuilt from PROJECT_GUIDE.md so the tests can run
outside the repo:   cd backend && PYTHONPATH=tests/sandbox_repo pytest tests/resumes
Never copy this folder into your repo. (No __init__.py files on purpose: it merges with backend/app as namespace
packages.)
