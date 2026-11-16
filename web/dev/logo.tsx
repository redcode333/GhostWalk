// Dev-only harness (not part of the production build): renders the real Logo large on a plain background so the load sequence can be recorded.
//   /dev/logo.html?theme=light|dark
import { createRoot } from "react-dom/client"
import "../src/styles.css"
import { Logo } from "../src/components/Logo"

const dark = new URLSearchParams(location.search).get("theme") === "dark"
document.documentElement.classList.toggle("dark", dark)
document.body.style.background = "var(--bg)"
createRoot(document.getElementById("r")!).render(<a href="/" aria-label="GhostWalk home" style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh", color: "inherit" }}><Logo width={200} size={76} /></a>)
