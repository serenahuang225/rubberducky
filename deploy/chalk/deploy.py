"""Deploy the self-contained, password-protected Claude demo to Chalk."""
from pathlib import Path
import os
from chalkcompute import Image, ScalingGroup, StartupProbe, Volume, Secret

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("DEMO_SOURCE_ROOT", str(ROOT)))

if __name__ == "__main__":
    from dotenv import dotenv_values
    settings = dotenv_values(ROOT / ".env.local")
    if not settings.get("ANTHROPIC_API_KEY") or not settings.get("ANTHROPIC_MODEL"):
        raise SystemExit("ANTHROPIC_API_KEY and ANTHROPIC_MODEL are required in .env.local")
    env = {"TUTOR_PROVIDER": "claude", "EXTERNAL_INTEGRATIONS_ENABLED": "true",
           "DEMO_BOOTSTRAP_ENABLED": "true", "TUTOR_ENV_FILE": "",
           "ANTHROPIC_MODEL": settings["ANTHROPIC_MODEL"],
           "FACTORY_INTERACTIVES_ENABLED": "false", "DAYTONA_CHECKS_ENABLED": "false"}
    secrets = [Secret.from_chalk_env("RUBBERDUCKY_ANTHROPIC_API_KEY", alias="ANTHROPIC_API_KEY"),
               Secret.from_chalk_env("RUBBERDUCKY_DEMO_ACCESS_PASSWORD", alias="DEMO_ACCESS_PASSWORD")]
    if settings.get("ANTHROPIC_WORKSPACE_ID"):
        env["ANTHROPIC_WORKSPACE_ID"] = settings["ANTHROPIC_WORKSPACE_ID"]
    requirements = [line.strip() for line in (SOURCE / "backend/requirements.in").read_text().splitlines()
                    if line.strip() and not line.startswith(("torch", "transformers", "peft", "accelerate", "safetensors", "huggingface-hub", "pytest", "ruff", "mypy", "chalkcompute"))]
    image = (Image.debian_slim("3.12").pip_install(requirements)
             .add_local_dir(str(SOURCE / "backend/app"), "/app/backend/app", strategy="volume", exclude=["**/__pycache__/**", "**/*.pyc"])
             .add_local_dir(str(SOURCE / "backend/migrations"), "/app/backend/migrations", strategy="volume")
             .add_local_file(str(SOURCE / "backend/alembic.ini"), "/app/backend/alembic.ini", strategy="copy")
             .add_local_dir(str(SOURCE / "frontend/dist"), "/app/web", strategy="volume")
             .add_local_file(str(ROOT / "deploy/chalk/serve.py"), "/app/backend/demo_serve.py", strategy="copy")
             .add_local_file(str(ROOT / "deploy/chalk/access.py"), "/app/backend/demo_access.py", strategy="copy")
             .workdir("/app/backend"))
    group = ScalingGroup(name="rubberducky-demo", image=image, cpu="500m", memory="1Gi",
                         min_replicas=1, max_replicas=1, port=8080,
                         volumes=[(Volume("rubberducky-demo-data"), "/data")],
                         env=env, secrets=secrets,
                         entrypoint=["python", "-m", "uvicorn", "demo_serve:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"],
                         startup_probe=StartupProbe.http("/api/health"),
                         tags={"app": "rubberducky", "purpose": "public-demo"})
    group.deploy(build_timeout=900, ready_timeout=600)
    print("DEMO_URL=" + str(group.web_url))
