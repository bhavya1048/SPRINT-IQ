import math
from datetime import date

from .allocation import candidate_score, member_workload, sprint_capacity


RISK_CATEGORIES = {
    "deadlines": "Deadlines",
    "workload": "Workload",
    "sprint_completion": "Sprint completion",
    "assignments": "Task assignment",
}

RISK_TYPES = {
    "overdue_task": "Overdue task",
    "deadline_approaching": "Deadline approaching",
    "overloaded_member": "Overloaded member",
    "sprint_completion": "Sprint completion risk",
    "unassigned_task": "Unassigned task",
    "no_eligible_assignee": "No eligible assignee",
    "unsuitable_assignment": "Unsuitable assignment",
}

RISK_SEVERITIES = ("HIGH", "MEDIUM", "LOW")
SEVERITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
HIGH_PRIORITY_TASKS = {"high", "critical"}
TASK_SEVERITY = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
    "critical": "HIGH",
}

DEFAULT_THRESHOLDS = {
    "RISK_DEADLINE_WARNING_DAYS": 5,
    "RISK_DEADLINE_HIGH_DAYS": 1,
    "RISK_DEADLINE_MEDIUM_DAYS": 3,
    "RISK_OVERDUE_MEDIUM_DAYS": 3,
    "RISK_OVERDUE_HIGH_DAYS": 8,
    "RISK_OVERLOAD_MEDIUM_PERCENT": 110,
    "RISK_OVERLOAD_HIGH_PERCENT": 125,
    "RISK_SPRINT_WARNING_DAYS": 5,
    "RISK_SPRINT_LOW_LOAD_RATIO": 0.7,
    "RISK_SPRINT_MEDIUM_LOAD_RATIO": 0.85,
    "RISK_SPRINT_HIGH_LOAD_RATIO": 1.0,
    "ALLOCATION_UNDERUTILIZED_THRESHOLD": 50,
    "ALLOCATION_OVERLOAD_THRESHOLD": 100,
}


def _thresholds(settings):
    settings = settings or {}
    values = {}
    for key, default in DEFAULT_THRESHOLDS.items():
        value = float(settings.get(key, default))
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite, non-negative number.")
        values[key] = value

    if not (
        values["RISK_DEADLINE_HIGH_DAYS"]
        <= values["RISK_DEADLINE_MEDIUM_DAYS"]
        <= values["RISK_DEADLINE_WARNING_DAYS"]
    ):
        raise ValueError("Deadline severity days must be ordered within the warning window.")
    if not (
        values["RISK_OVERDUE_MEDIUM_DAYS"]
        <= values["RISK_OVERDUE_HIGH_DAYS"]
    ):
        raise ValueError("Overdue severity days must be ordered.")
    if not (
        values["RISK_OVERLOAD_MEDIUM_PERCENT"]
        < values["RISK_OVERLOAD_HIGH_PERCENT"]
    ):
        raise ValueError("Overload severity percentages must be ordered.")
    if not (
        values["RISK_SPRINT_LOW_LOAD_RATIO"]
        <= values["RISK_SPRINT_MEDIUM_LOAD_RATIO"]
        <= values["RISK_SPRINT_HIGH_LOAD_RATIO"]
    ):
        raise ValueError("Sprint load severity ratios must be ordered.")
    return values


def _task_severity(task):
    return TASK_SEVERITY.get((task.priority or "").casefold(), "MEDIUM")


def _alert(
    risk_type,
    category,
    severity,
    description,
    reason,
    action,
    sprint,
    task=None,
    team_member=None,
):
    project = sprint.project
    return {
        "risk_type": risk_type,
        "risk_label": RISK_TYPES[risk_type],
        "category": category,
        "category_label": RISK_CATEGORIES[category],
        "severity": severity,
        "description": description,
        "project": project,
        "project_id": project.id,
        "sprint": sprint,
        "sprint_id": sprint.id,
        "task": task,
        "task_id": task.id if task else None,
        "team_member": team_member,
        "team_member_id": team_member.id if team_member else None,
        "reason": reason,
        "action": action,
    }


def build_risk_alerts(sprints, tasks, members, as_of=None, settings=None):
    """Return unique, deterministic risk alerts for the supplied workspace scope."""
    as_of = as_of or date.today()
    thresholds = _thresholds(settings)
    sprint_ids = {sprint.id for sprint in sprints}
    tasks_by_sprint = {sprint_id: [] for sprint_id in sprint_ids}
    for task in tasks:
        if task.sprint_id in tasks_by_sprint:
            tasks_by_sprint[task.sprint_id].append(task)

    alerts = []
    seen = set()

    def add_alert(alert, entity_id):
        key = (alert["risk_type"], entity_id, alert["sprint_id"])
        if key not in seen:
            seen.add(key)
            alerts.append(alert)

    unfinished_tasks = [
        task for task in tasks
        if task.sprint_id in sprint_ids and (task.status or "").casefold() != "done"
    ]

    for task in unfinished_tasks:
        sprint = task.sprint
        if task.due_date is None:
            continue
        days_until_due = (task.due_date - as_of).days
        if days_until_due < 0:
            overdue_days = -days_until_due
            if overdue_days >= thresholds["RISK_OVERDUE_HIGH_DAYS"]:
                severity = "HIGH"
            elif overdue_days >= thresholds["RISK_OVERDUE_MEDIUM_DAYS"]:
                severity = "MEDIUM"
            else:
                severity = "LOW"
            add_alert(
                _alert(
                    "overdue_task",
                    "deadlines",
                    severity,
                    f"{task.title} is {overdue_days} day(s) overdue.",
                    f"Its deadline was {task.due_date}; it remains unfinished.",
                    "Review the remaining work, update the deadline, or reassign it.",
                    sprint,
                    task=task,
                ),
                task.id,
            )
        elif (
            (task.priority or "").casefold() in HIGH_PRIORITY_TASKS
            and days_until_due <= thresholds["RISK_DEADLINE_WARNING_DAYS"]
        ):
            if days_until_due <= thresholds["RISK_DEADLINE_HIGH_DAYS"]:
                severity = "HIGH"
            elif days_until_due <= thresholds["RISK_DEADLINE_MEDIUM_DAYS"]:
                severity = "MEDIUM"
            else:
                severity = "LOW"
            add_alert(
                _alert(
                    "deadline_approaching",
                    "deadlines",
                    severity,
                    f"{task.title} is due in {days_until_due} day(s).",
                    f"It is unfinished, has {task.priority.title()} priority, and is inside the "
                    f"{int(thresholds['RISK_DEADLINE_WARNING_DAYS'])}-day warning window.",
                    "Confirm an owner and review the task plan before its deadline.",
                    sprint,
                    task=task,
                ),
                task.id,
            )

    for sprint in sprints:
        if (sprint.status or "").casefold() == "completed":
            continue
        for member in members:
            workload = member_workload(
                member,
                sprint,
                underutilized_threshold=thresholds[
                    "ALLOCATION_UNDERUTILIZED_THRESHOLD"
                ],
                overload_threshold=thresholds["ALLOCATION_OVERLOAD_THRESHOLD"],
            )
            if workload["allocated"] <= workload["capacity"]:
                continue
            utilization = (
                100.0 * workload["allocated"] / workload["capacity"]
                if workload["capacity"]
                else math.inf
            )
            if utilization >= thresholds["RISK_OVERLOAD_HIGH_PERCENT"]:
                severity = "HIGH"
            elif utilization >= thresholds["RISK_OVERLOAD_MEDIUM_PERCENT"]:
                severity = "MEDIUM"
            else:
                severity = "LOW"
            add_alert(
                _alert(
                    "overloaded_member",
                    "workload",
                    severity,
                    f"{member.name} has more work allocated than their sprint capacity.",
                    f"{workload['allocated']:.1f}h is allocated against "
                    f"{workload['capacity']:.1f}h available "
                    f"({utilization:.1f}% utilization).",
                    "Reduce or redistribute assignments, or explicitly review capacity.",
                    sprint,
                    team_member=member,
                ),
                member.id,
            )

    for sprint in sprints:
        if (sprint.status or "").casefold() == "completed":
            continue
        days_until_end = (sprint.end_date - as_of).days
        if (
            sprint.start_date > as_of
            or days_until_end < 0
            or days_until_end > thresholds["RISK_SPRINT_WARNING_DAYS"]
        ):
            continue
        open_tasks = tasks_by_sprint[sprint.id]
        open_tasks = [
            task for task in open_tasks
            if (task.status or "").casefold() != "done"
        ]
        remaining_effort = sum(float(task.estimated_hours or 0) for task in open_tasks)
        if remaining_effort <= 0:
            continue
        available_capacity = sum(
            sprint_capacity(member, sprint)["capacity"] for member in members
        )
        load_ratio = (
            remaining_effort / available_capacity
            if available_capacity > 0
            else math.inf
        )
        if load_ratio < thresholds["RISK_SPRINT_LOW_LOAD_RATIO"]:
            continue
        if load_ratio >= thresholds["RISK_SPRINT_HIGH_LOAD_RATIO"]:
            severity = "HIGH"
        elif load_ratio >= thresholds["RISK_SPRINT_MEDIUM_LOAD_RATIO"]:
            severity = "MEDIUM"
        else:
            severity = "LOW"
        related_task = (
            max(open_tasks, key=lambda task: float(task.estimated_hours or 0))
            if open_tasks
            else None
        )
        capacity_description = (
            f"{available_capacity:.1f}h available"
            if available_capacity > 0
            else "no available team capacity"
        )
        ratio_description = (
            f"{load_ratio:.0%} of available capacity"
            if math.isfinite(load_ratio)
            else "more effort than the zero available capacity can cover"
        )
        add_alert(
            _alert(
                "sprint_completion",
                "sprint_completion",
                severity,
                f"{sprint.name} has substantial work remaining near its end date.",
                f"{remaining_effort:.1f}h remains with {capacity_description}; "
                f"this is {ratio_description}.",
                "Re-estimate remaining work, reduce scope, or rebalance capacity before sprint end.",
                sprint,
                task=related_task,
            ),
            sprint.id,
        )

    for task in unfinished_tasks:
        sprint = task.sprint
        assigned_members = [assignment.team_member for assignment in task.assignments]
        evaluations = {}
        for member in members:
            workload = member_workload(
                member,
                sprint,
                underutilized_threshold=thresholds[
                    "ALLOCATION_UNDERUTILIZED_THRESHOLD"
                ],
                overload_threshold=thresholds["ALLOCATION_OVERLOAD_THRESHOLD"],
                exclude_task_id=task.id,
            )
            evaluations[member.id] = candidate_score(task, workload)
        eligible_members = [
            member
            for member in members
            if evaluations[member.id]["eligible"]
        ]

        if not assigned_members:
            if eligible_members:
                risk_type = "unassigned_task"
                reason = (
                    "The task has no assignment, although "
                    f"{len(eligible_members)} team member(s) currently meet Phase 4 "
                    "skill and capacity eligibility rules."
                )
                action = "Assign an eligible member and confirm the effort estimate."
            else:
                risk_type = "no_eligible_assignee"
                reason = (
                    "The task has no assignment and no team member currently meets "
                    "the required-skill and remaining-capacity rules."
                )
                action = (
                    "Review required skills and effort, add suitable capacity, or "
                    "make a manager-approved override."
                )
            add_alert(
                _alert(
                    risk_type,
                    "assignments",
                    _task_severity(task),
                    f"{task.title} has no assigned team member.",
                    reason,
                    action,
                    sprint,
                    task=task,
                ),
                task.id,
            )
        elif not any(
            evaluations.get(member.id, {}).get("eligible", False)
            for member in assigned_members
        ):
            reasons = sorted(
                {
                    reason
                    for member in assigned_members
                    for reason in evaluations.get(member.id, {}).get(
                        "ineligibility_reasons", ()
                    )
                }
            )
            detail = " ".join(reasons) or "No assigned member currently meets eligibility rules."
            add_alert(
                _alert(
                    "unsuitable_assignment",
                    "assignments",
                    _task_severity(task),
                    f"{task.title} has no currently eligible assigned member.",
                    detail,
                    "Review the assignment against required skills and remaining sprint capacity.",
                    sprint,
                    task=task,
                ),
                task.id,
            )

    alerts.sort(
        key=lambda alert: (
            SEVERITY_RANK[alert["severity"]],
            alert["project"].name.casefold(),
            alert["sprint"].name.casefold(),
            alert["risk_type"],
            alert["task"].title.casefold() if alert["task"] else "",
            alert["team_member"].name.casefold() if alert["team_member"] else "",
        )
    )
    return alerts
