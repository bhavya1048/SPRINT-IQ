(() => {
  const project = document.getElementById("risk-project-filter");
  const sprint = document.getElementById("risk-sprint-filter");
  if (!project || !sprint) return;

  project.addEventListener("change", () => {
    const selected = sprint.selectedOptions[0];
    if (
      selected &&
      selected.value &&
      project.value &&
      selected.dataset.projectId !== project.value
    ) {
      sprint.value = "";
    }
  });
})();
