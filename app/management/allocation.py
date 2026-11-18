import math
import re
from datetime import timedelta


ALLOCATION_WEIGHTS = {
    "skill_match": 0.40,
    "capacity_score": 0.30,
    "availability_score": 0.20,
    "priority_suitability": 0.10,
}
PRIORITY_SUITABILITY = {
    "low": 60,
    "medium": 75,
    "high": 90,
    "critical": 100,
}


def parse_skills(skills):
    return {
        skill.strip().casefold()
        for skill in re.split(r"[,;\n]+", skills or "")
        if skill.strip()
    }


def skill_match_score(required_skills, member_skills):
    required = parse_skills(required_skills)
    if not required:
        return 100.0
    available = parse_skills(member_skills)
    return round(100.0 * len(required & available) / len(required), 2)


def count_working_days(sprint):
    current = sprint.start_date
    days = 0
    while current <= sprint.end_date:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def _hours(value):
    hours = float(value or 0)
    if not math.isfinite(hours) or hours < 0:
        raise ValueError("Stored capacity and assignment hours must be finite and non-negative.")
    return hours


def _workload_totals(member, capacity, theoretical_capacity, allocated, underutilized_threshold, overload_threshold):
    remaining = capacity - allocated
    utilization = 100.0 * allocated / capacity if capacity else (100.0 if allocated else 0.0)
    if (capacity == 0 and allocated > 0) or utilization > overload_threshold:
        classification = "overloaded"
    elif capacity > 0 and utilization < underutilized_threshold:
        classification = "underutilized"
    else:
        classification = "balanced"
    availability_score = (
        100.0 * capacity / theoretical_capacity if theoretical_capacity else 0.0
    )
    return {
        "member": member,
        "member_id": member.id,
        "capacity": round(capacity, 2),
        "theoretical_capacity": round(theoretical_capacity, 2),
        "availability_score": round(availability_score, 2),
        "allocated": round(allocated, 2),
        "remaining": round(remaining, 2),
        "utilization": round(utilization, 2),
        "classification": classification,
    }


def sprint_capacity(member, sprint):
    working_days = count_working_days(sprint)
    daily_capacity = _hours(member.daily_capacity)
    stored_availability = _hours(member.available_hours)
    theoretical_capacity = daily_capacity * working_days
    capacity = min(stored_availability, theoretical_capacity)
    availability_score = (
        100.0 * capacity / theoretical_capacity if theoretical_capacity else 0.0
    )
    return {
        "working_days": working_days,
        "theoretical_capacity": round(theoretical_capacity, 2),
        "capacity": round(capacity, 2),
        "availability_score": round(availability_score, 2),
    }


def member_workload(
    member,
    sprint,
    underutilized_threshold=50,
    overload_threshold=100,
    exclude_task_id=None,
):
    capacity_data = sprint_capacity(member, sprint)
    allocated = sum(
        _hours(assignment.assigned_hours)
        for assignment in member.assignments
        if assignment.task.sprint_id == sprint.id
        and assignment.task_id != exclude_task_id
    )
    return _workload_totals(
        member,
        capacity_data["capacity"],
        capacity_data["theoretical_capacity"],
        allocated,
        underutilized_threshold,
        overload_threshold,
    )


def aggregate_member_workloads(
    member,
    sprint_workloads,
    underutilized_threshold=50,
    overload_threshold=100,
):
    if not sprint_workloads:
        return {
            "member": member,
            "member_id": member.id,
            "capacity": 0.0,
            "theoretical_capacity": 0.0,
            "availability_score": 0.0,
            "allocated": 0.0,
            "remaining": 0.0,
            "utilization": 0.0,
            "classification": "no_data",
        }
    return _workload_totals(
        member,
        sum(workload["capacity"] for workload in sprint_workloads),
        sum(workload["theoretical_capacity"] for workload in sprint_workloads),
        sum(workload["allocated"] for workload in sprint_workloads),
        underutilized_threshold,
        overload_threshold,
    )


def candidate_score(task, workload):
    member = workload["member"]
    requirements = parse_skills(task.required_skills)
    member_skills = parse_skills(member.skills)
    skill_score = skill_match_score(task.required_skills, member.skills)
    capacity = workload["capacity"]
    remaining = workload["remaining"]
    effort = _hours(task.estimated_hours)
    capacity_score = (
        max(0.0, min(100.0, 100.0 * remaining / capacity)) if capacity else 0.0
    )
    priority_base = PRIORITY_SUITABILITY.get((task.priority or "").casefold(), 75)
    priority_suitability = priority_base * skill_score / 100.0
    projected_utilization = (
        100.0 * (workload["allocated"] + effort) / capacity if capacity else 100.0
    )

    ineligibility_reasons = []
    missing_skills = sorted(requirements - member_skills)
    if requirements and skill_score == 0:
        ineligibility_reasons.append("No required skills match.")
    if capacity <= 0 or remaining < effort:
        ineligibility_reasons.append("Insufficient remaining sprint capacity.")

    score = (
        ALLOCATION_WEIGHTS["skill_match"] * skill_score
        + ALLOCATION_WEIGHTS["capacity_score"] * capacity_score
        + ALLOCATION_WEIGHTS["availability_score"] * workload["availability_score"]
        + ALLOCATION_WEIGHTS["priority_suitability"] * priority_suitability
    )
    skill_explanation = (
        "No required skills specified; skill match is neutral."
        if not requirements
        else f"{len(requirements) - len(missing_skills)}/{len(requirements)} required skills match."
    )
    if missing_skills and skill_score > 0:
        skill_explanation += " Missing: " + ", ".join(missing_skills) + "."

    return {
        "member": member,
        "member_id": member.id,
        "eligible": not ineligibility_reasons,
        "ineligibility_reasons": ineligibility_reasons,
        "score": round(max(0.0, min(100.0, score)), 2),
        "skill_match": skill_score,
        "capacity_score": round(capacity_score, 2),
        "availability_score": workload["availability_score"],
        "priority_suitability": round(priority_suitability, 2),
        "remaining_capacity": remaining,
        "projected_remaining_capacity": round(remaining - effort, 2),
        "utilization": workload["utilization"],
        "projected_utilization": round(projected_utilization, 2),
        "explanations": {
            "skills": skill_explanation,
            "capacity": (
                f"{remaining:.1f}h remains; {effort:.1f}h requested."
            ),
            "availability": (
                f"{workload['availability_score']:.1f}% of calculated sprint capacity "
                "is available from stored member capacity."
            ),
            "workload": (
                f"Utilization would change from {workload['utilization']:.1f}% "
                f"to {projected_utilization:.1f}%."
            ),
        },
    }


def ranked_recommendations(task, workloads, rejected_member_ids=()):
    rejected = set(rejected_member_ids)
    recommendations = [
        candidate_score(task, workload)
        for workload in workloads
        if workload["member_id"] not in rejected
    ]
    eligible = [recommendation for recommendation in recommendations if recommendation["eligible"]]
    return sorted(
        eligible,
        key=lambda recommendation: (
            -recommendation["score"],
            recommendation["member"].name.casefold(),
        ),
    )
