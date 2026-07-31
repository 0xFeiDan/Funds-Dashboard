module.exports = {
  apps: [{
    name: "funds-dashboard",
    cwd: "./backend",
    script: "./.venv/bin/uvicorn",
    args: "app.main:app --host 0.0.0.0 --port 8089",
    interpreter: "none",
    env: { PYTHONUNBUFFERED: "1" },
    max_restarts: 10,
    restart_delay: 3000,
  }],
};
