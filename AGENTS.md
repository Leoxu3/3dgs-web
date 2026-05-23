# AGENTS.md

This document provides implementation instructions for Codex / coding agents working on this repository.

The goal is to build a server-friendly, Web GUI based 3D Gaussian Splatting viewer. The user should be able to interactively control the camera. After the camera becomes idle, the current rendered view should be automatically sent to Difix3D / Difix3D+ for refinement, and the refined result should be displayed in the browser.

---

## 1. Project Goal

The goal of this final project is not to retrain 3D Gaussian Splatting. Instead, the objective is to build a demoable interactive system.

The system should:

1. Load an existing 3D Gaussian Splatting `.ply` file.
2. Provide real-time camera interaction in the browser.
3. Display the raw 3DGS render while the user is dragging, rotating, or zooming the camera.
4. After the user stops interacting for a short period of time, automatically capture the current rendered viewpoint.
5. Send the captured image to the backend and run single-image / single-frame refinement using Difix3D / Difix3D+.
6. Display the refinement result in the same Web UI.

The UI should preferably support:

- raw / refined switching;
- side-by-side comparison;
- latency display;
- refinement running status.

The grading priority is demo completeness and clarity of the interaction pipeline, not a completely novel research contribution.

---

## 2. Important Constraints and Design Decisions

### 2.1 Server Environment First

This project is expected to run mainly on a lab / cluster server.

Therefore:

- Do not use GUI frameworks that require a desktop environment, such as:
  - PyQt
  - DearPyGui
  - OpenCV `imshow`
  - Tkinter
- The GUI should be implemented as a Web interface.
- The Web server should be able to bind to `0.0.0.0`, so it can be accessed through SSH tunneling or a browser.
- Do not assume that the server has X11, Wayland, or a physical display.
- CUDA / GPU availability may be assumed.

### 2.2 Demo First, Completeness Later

Prioritize a working MVP before improving performance or quality.

The MVP should include:

1. A Web viewer.
2. Interactive camera control.
3. Camera idle detection that triggers a refinement request.
4. A backend that can return a refined image.
5. A fallback mode: if Difix3D is not installed or cannot run, the backend should directly return the input image and the UI should show `Difix3D unavailable / fallback mode`.

### 2.3 Preferred Web Viewer Architecture

Frontend Web UI:

- Display the current rendered image.
- Support mouse drag / keyboard camera control.
- Use debounce-based idle detection.

Backend:

- Use FastAPI / WebSocket where appropriate.
- Load the 3DGS `.ply` file.
- Render the current camera view using `gsplat`.
- During interaction:
  - render at lower resolution;
  - do not run refinement.
- After the camera becomes idle:
  - render or capture a higher-resolution image;
  - run Difix3D refinement;
  - return the refined image to the frontend.

---

## 3. Suggested Repository Structure

Organize the project into multiple files and directories according to their responsibilities.

Keep the structure readable and maintainable.

---

## 4. Environment Setup Rules

Codex may create a virtual environment and install missing packages.

Prefer using `conda` for environment setup.

---

## 5. UI Requirements

The Web UI should include at least:

1. A main viewer area.
2. Raw / refined display modes:

   * Raw only
   * Refined overlay
   * Side-by-side
3. A status bar showing:

   * Camera moving / idle
   * Refining...
   * Refine done
   * Fallback mode
   * Error message
4. Scene / PLY path display.
5. FPS or render time display, if easy to implement.
6. Refinement latency display.

The refinement result must not block the user from continuing to move the camera.

---

## 6. Success Criteria

When the project is complete, it should be possible to:

1. Start the backend and frontend on a server with one command.
2. Open the viewer in a browser.
3. Interactively control the 3DGS scene camera.
4. Keep the viewer responsive while the camera is moving.
5. Automatically refine the current view after the camera becomes idle.
6. Display raw and refined results for comparison.
7. Demonstrate the pipeline even when Difix3D is unavailable, using fallback mode.
8. Provide a README that allows another person to reproduce the demo.

---

## 7. Additional Instructions for Codex

* You may install missing packages.
* You may add scripts, tests, and a README.
* If you encounter dependency issues, ask before making risky changes.
* After completing each phase, run the corresponding test or minimal startup check.
* If a 3DGS viewer package does not support the current PLY format, document the reason and try a reasonable alternative.
* Avoid dependencies that require a GUI display.

