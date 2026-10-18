import { httpTutor } from "./tutorHttp.ts";
import { photonStatus, runPhoton } from "./live.ts";

const env = process.env;
const status = photonStatus(env);
if (status !== "ready") {
  console.log(
    status === "disabled"
      ? "Photon messaging is off. Set PHOTON_MESSAGING_ENABLED=true to connect."
      : "Photon messaging needs SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET.",
  );
} else {
  const base = env.TUTOR_API_BASE_URL ?? "http://127.0.0.1:3100";
  await runPhoton(env, httpTutor(base));
}
