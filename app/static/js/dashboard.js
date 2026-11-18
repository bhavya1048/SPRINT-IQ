(() => {
  const projectFilter = document.getElementById("project-filter");
  const sprintFilter = document.getElementById("sprint-filter");
  if (projectFilter && sprintFilter) {
    projectFilter.addEventListener("change", () => {
      const selectedSprint = sprintFilter.selectedOptions[0];
      if (
        selectedSprint &&
        selectedSprint.value &&
        projectFilter.value &&
        selectedSprint.dataset.projectId !== projectFilter.value
      ) {
        sprintFilter.value = "";
      }
    });
  }

  const dataElement = document.getElementById("dashboard-chart-data");
  if (!dataElement) return;

  let dashboardData;
  try {
    dashboardData = JSON.parse(dataElement.textContent);
  } catch (error) {
    document.querySelectorAll(".dashboard-chart-wrap").forEach((container) => {
      container.textContent = "Chart data could not be loaded.";
    });
    return;
  }

  if (typeof window.Chart !== "function") {
    document.querySelectorAll(".dashboard-chart-wrap").forEach((container) => {
      container.textContent = "Charts are unavailable. Check your connection and reload.";
    });
    return;
  }

  const colors = {
    violet: "#7c3aed",
    cyan: "#06b6d4",
    green: "#10b981",
    amber: "#f59e0b",
    red: "#ef4444",
    muted: "#9ca3af",
  };
  const gridColor = "rgba(107, 114, 128, 0.12)";
  const legend = {
    position: "bottom",
    labels: { usePointStyle: true, padding: 18 },
  };

  const createChart = (id, config) => {
    const canvas = document.getElementById(id);
    if (canvas) new window.Chart(canvas, config);
  };

  createChart("task-status-chart", {
    type: "doughnut",
    data: {
      labels: dashboardData.status.labels,
      datasets: [{
        data: dashboardData.status.values,
        backgroundColor: [colors.violet, colors.cyan, colors.green, colors.muted],
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend },
      cutout: "64%",
    },
  });

  createChart("task-priority-chart", {
    type: "bar",
    data: {
      labels: dashboardData.priority.labels,
      datasets: [{
        label: "Tasks",
        data: dashboardData.priority.values,
        backgroundColor: [colors.cyan, colors.violet, colors.amber, colors.red, colors.muted],
        borderRadius: 6,
        maxBarThickness: 48,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: gridColor } },
      },
    },
  });

  createChart("sprint-progress-chart", {
    type: "bar",
    data: {
      labels: dashboardData.sprint_progress.labels,
      datasets: [{
        label: "Completion",
        data: dashboardData.sprint_progress.values,
        backgroundColor: colors.green,
        borderRadius: 6,
        maxBarThickness: 32,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (context) => `${context.raw}% complete` } },
      },
      scales: {
        x: {
          min: 0,
          max: 100,
          ticks: { callback: (value) => `${value}%` },
          grid: { color: gridColor },
        },
        y: { grid: { display: false } },
      },
    },
  });

  createChart("team-workload-chart", {
    type: "bar",
    data: {
      labels: dashboardData.workload.labels,
      datasets: [
        {
          label: "Allocated hours",
          data: dashboardData.workload.allocated,
          backgroundColor: colors.violet,
          borderRadius: 5,
        },
        {
          label: "Remaining capacity",
          data: dashboardData.workload.remaining,
          backgroundColor: colors.cyan,
          borderRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend },
      scales: {
        x: { grid: { display: false } },
        y: {
          beginAtZero: true,
          title: { display: true, text: "Hours" },
          grid: { color: gridColor },
        },
      },
    },
  });
})();
