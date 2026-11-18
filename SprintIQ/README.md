# SprintIQ

**Intelligent Agile Sprint Planning and Workload Balancing System**

A Flask-based web application for Agile sprint planning and workload balancing. It includes SQLAlchemy domain models, session-based authentication, and project, sprint, team, and task management with a Kanban board.

## Current features
- Flask application factory and modular blueprint structure
- SQLite database configuration via Flask-SQLAlchemy with additive legacy-user schema upgrades
- Responsive UI with Bootstrap 5
- Health‑check endpoint
- User registration, login, and POST-only logout with hashed passwords and CSRF protection
- Login-protected dashboard and administrator-only placeholder route
- User, project, team member, sprint, task, and task assignment models
- Project CRUD with owner association and owner-aware project-manager permissions
- Sprint CRUD with project/date validation
- Team member CRUD with unique email addresses and optional account linking
- Task CRUD, multi-member assignment, and To Do / In Progress / Done Kanban status updates
- Additive SQLite upgrades for project owners and team member emails; existing records are retained

## Quick start

From the project root, create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run the test suite with `python -m pytest -q`.

Start the application:

```powershell
python run.py
```

Open `http://127.0.0.1:5000/` in your browser. Register an account at `/auth/register`, then sign in at `/auth/login` to access the dashboard. Public registration assigns the `team_member` role; administrator and project-manager roles must be assigned by a trusted operator. The health-check endpoint is available at `http://127.0.0.1:5000/health`.

The app creates missing tables at startup and applies additive SQLite schema upgrades without dropping existing rows. Administrators and project managers must be assigned by a trusted operator. Administrators can manage all records. Project managers can manage projects they own, including their sprints and tasks, and can manage team members. Authenticated users can view workspace records; linked task assignees can update their task status. Back up the database before deploying schema changes to important data.

## Project structure
```
SprintIQ/
├─ app/
│  ├─ __init__.py          # Application factory
│  ├─ models.py            # SQLAlchemy model definitions
│  ├─ main/                # Core routes (dashboard, health)
│  │   ├─ __init__.py
│  │   └─ routes.py
│  ├─ management/          # Project, sprint, team, and task workflows
│  │   ├─ forms.py
│  │   └─ routes.py
│  ├─ templates/           # Jinja2 templates
│  └─ static/              # CSS / JS assets
├─ requirements.txt
├─ config.py
├─ run.py
└─ .gitignore
```

## License
MIT. Feel free to adapt for your capstone project.
