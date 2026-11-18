from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    FloatField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    InputRequired,
    Length,
    NumberRange,
    Optional,
)


class ProjectForm(FlaskForm):
    name = StringField("Project name", validators=[DataRequired(), Length(max=120)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=5000)])
    start_date = DateField("Start date", validators=[Optional()])
    end_date = DateField("End date", validators=[Optional()])
    status = SelectField(
        "Status",
        choices={
            "planning": "Planning",
            "active": "Active",
            "completed": "Completed",
            "archived": "Archived",
        },
        validators=[DataRequired()],
        default="planning",
    )
    submit = SubmitField("Save project")


class SprintForm(FlaskForm):
    name = StringField("Sprint name", validators=[DataRequired(), Length(max=120)])
    sprint_goal = TextAreaField("Sprint goal", validators=[Optional(), Length(max=5000)])
    start_date = DateField("Start date", validators=[DataRequired()])
    end_date = DateField("End date", validators=[DataRequired()])
    status = SelectField(
        "Status",
        choices={
            "planned": "Planned",
            "active": "Active",
            "completed": "Completed",
        },
        validators=[DataRequired()],
        default="planned",
    )
    submit = SubmitField("Save sprint")


class TeamMemberForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    skills = TextAreaField("Technical skills", validators=[Optional(), Length(max=2000)])
    available_hours = FloatField(
        "Available sprint hours", validators=[InputRequired(), NumberRange(min=0)]
    )
    daily_capacity = FloatField(
        "Daily capacity (hours)", validators=[InputRequired(), NumberRange(min=0)]
    )
    submit = SubmitField("Save team member")


class TaskForm(FlaskForm):
    sprint_id = SelectField("Project / sprint", validators=[DataRequired()])
    title = StringField("Task title", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=10000)])
    priority = SelectField(
        "Priority",
        choices={
            "low": "Low",
            "medium": "Medium",
            "high": "High",
            "critical": "Critical",
        },
        validators=[DataRequired()],
        default="medium",
    )
    estimated_hours = FloatField(
        "Estimated effort (hours)", validators=[InputRequired(), NumberRange(min=0)]
    )
    status = SelectField(
        "Status",
        choices={"todo": "To Do", "in_progress": "In Progress", "done": "Done"},
        validators=[DataRequired()],
        default="todo",
    )
    due_date = DateField("Deadline", validators=[Optional()])
    team_member_ids = SelectMultipleField("Assigned team members", coerce=int)
    assigned_hours = FloatField(
        "Assigned hours per member",
        validators=[Optional(), NumberRange(min=0)],
        default=0,
    )
    submit = SubmitField("Save task")
