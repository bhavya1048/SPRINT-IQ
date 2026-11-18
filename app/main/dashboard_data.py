from collections import Counter, defaultdict

from ..management.allocation import aggregate_member_workloads, member_workload


TASK_STATUS_LABELS = {
    "todo": "To Do",
    "pending": "To Do",
    "in_progress": "In Progress",
    "done": "Done",
}
TASK_PRIORITY_LABELS = ("low", "medium", "high", "critical")


def build_dashboard_data(
    projects,
    sprints,
    tasks,
    members,
    underutilized_threshold=50,
    overload_threshold=100,
):
    status_counts = Counter(
        TASK_STATUS_LABELS.get(task.status, "Other") for task in tasks
    )
    priority_counts = Counter(
        priority if priority in TASK_PRIORITY_LABELS else "other"
        for priority in (task.priority.casefold() for task in tasks)
    )
    completed_count = status_counts["Done"]
    pending_count = status_counts["To Do"]
    in_progress_count = status_counts["In Progress"]

    tasks_by_sprint = defaultdict(list)
    for task in tasks:
        tasks_by_sprint[task.sprint_id].append(task)

    sprint_progress = []
    for sprint in sprints:
        sprint_tasks = tasks_by_sprint[sprint.id]
        total_tasks = len(sprint_tasks)
        completed_tasks = sum(task.status == "done" for task in sprint_tasks)
        remaining_tasks = total_tasks - completed_tasks
        remaining_effort = sum(
            task.estimated_hours for task in sprint_tasks if task.status != "done"
        )
        completion = (
            100.0 * completed_tasks / total_tasks if total_tasks else 0.0
        )
        sprint_progress.append(
            {
                "id": sprint.id,
                "name": sprint.name,
                "project_name": sprint.project.name,
                "start_date": sprint.start_date,
                "end_date": sprint.end_date,
                "completion": round(completion, 2),
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "remaining_tasks": remaining_tasks,
                "remaining_effort": round(remaining_effort, 2),
            }
        )

    workloads = []
    for member in members:
        sprint_workloads = [
            member_workload(
                member,
                sprint,
                underutilized_threshold,
                overload_threshold,
            )
            for sprint in sprints
        ]
        workloads.append(
            aggregate_member_workloads(
                member,
                sprint_workloads,
                underutilized_threshold,
                overload_threshold,
            )
        )
    workloads.sort(key=lambda workload: workload["member"].name.casefold())

    chart_data = {
        "status": {
            "labels": ["To Do", "In Progress", "Done", "Other"],
            "values": [
                status_counts["To Do"],
                status_counts["In Progress"],
                status_counts["Done"],
                status_counts["Other"],
            ],
            "total": len(tasks),
        },
        "priority": {
            "labels": ["Low", "Medium", "High", "Critical", "Other"],
            "values": [
                priority_counts["low"],
                priority_counts["medium"],
                priority_counts["high"],
                priority_counts["critical"],
                priority_counts["other"],
            ],
            "total": len(tasks),
        },
        "workload": {
            "labels": [workload["member"].name for workload in workloads],
            "allocated": [workload["allocated"] for workload in workloads],
            "remaining": [workload["remaining"] for workload in workloads],
            "has_sprint_data": bool(sprints),
        },
        "sprint_progress": {
            "labels": [
                f'{sprint["project_name"]} / {sprint["name"]}'
                for sprint in sprint_progress
            ],
            "values": [sprint["completion"] for sprint in sprint_progress],
            "rows": sprint_progress,
        },
    }

    return {
        "total_projects": len(projects),
        "total_sprints": len(sprints),
        "total_tasks": len(tasks),
        "completed_tasks": completed_count,
        "pending_tasks": pending_count,
        "in_progress_tasks": in_progress_count,
        "total_team_members": len(members),
        "sprint_progress": sprint_progress,
        "workloads": workloads,
        "chart_data": chart_data,
    }
