# Technical Audit & Architecture Blueprint: Browser Fingerprint Randomness & Coherence Pipeline

## 1. Problem Statement & Observed Behavior

When an operator clicks **"New profile"** in the Persona Studio dashboard, the generated browser profile exhibits a **100% deterministic and static device fingerprint**. Multiple profiles created in sequence receive identical hardware and platform characteristics:
- **Operating System**: `Windows 10`
- **User-Agent**: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36`
- **Screen Resolution**: `1920x1080` (Index `[0]`)
- **CPU Hardware Concurrency**: `6 cores` (Index `[1]`)
- **Device Memory**: `16 GB` (Index `[1]`)
- **WebGL Vendor**: `Google Inc. (NVIDIA)`
- **WebGL Renderer**: `ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)` (Index `[0]`)

### Risk Impact
1. **Device Fingerprint Collision**: Target sites (e.g., Meta/Facebook Risk Engine, Cloudflare, PerimeterX) recognize multiple accounts as originating from the exact same hardware workstation.
2. **Dashboard Health Collisions**: Profiles trigger the `shared FP` warning badge via `/api/profiles/collisions` based on the hash function `fpSignature(p) = [p.os, p.userAgent, p.screen, p.cores, p.memory, p.webglRenderer].join("|")`.
3. **Canvas/Audio Noise Drift**: Due to unpersisted noise seeds, the Canvas and Audio noise values mutate across browser restarts rather than remaining stable for the given profile.

---

## 2. Root Cause Analysis & Code Anchors

### Root Cause 1: Hardcoded Static Indices in `newProfile()`
- **File**: `/home/gyoutu/src/persona-studio/dashboard/src/App.jsx`
- **Lines**: `1130–1142`
- **Implementation**:
  ```javascript
  function newProfile(folder, defaultEngine = ENGINE_ORDER[0]) {
    const os = "Windows";
    return {
      id: nid(), name: "", folder: folder === "All profiles" ? "Facebook Ads" : folder,
      status: "stopped", os, tags: [], engine: defaultEngine, browser: "Chrome", browserVersion: "151.0.0.0",
      userAgent: uaFor(os),
      screen: SCREENS[os][0],   // Always index 0: "1920x1080"
      cores: CORES[os][1],       // Always index 1: 6 cores
      memory: RAM[os][1],        // Always index 1: 16 GB
      webglVendor: "Google Inc. (NVIDIA)",
      webglRenderer: GPUS[os][0],// Always index 0: RTX 3060 Direct3D11
      canvas: "Noise", webrtc: "Altered", audio: "Noise", fonts: "Masked",
      locale: "en-US", timezone: "America/New_York", geo: "Prompt",
      mediaVideo: 1, mediaAudio: 1, dnt: false, proxy: null, notes: "", startupUrls: "", extensions: "",
      lastActive: "never", _new: true,
    };
  }
  ```
- **Mechanism**: The constructor initializes all device attributes using fixed zero/first indices. It does not invoke any randomization algorithm.

### Root Cause 2: Dead Code Generator `freshDevice()` Not Invoked in Single Creation
- **File**: `/home/gyoutu/src/persona-studio/dashboard/src/App.jsx`
- **Lines**: `313–323`
- **Implementation**:
  ```javascript
  function freshDevice(os, locale = "en-US") {
    const rnd = (arr) => arr[Math.floor(Math.random() * arr.length)];
    const chrome = rnd(CHROME_VERSIONS);
    const gpu = rnd(GPUS[os]);
    return {
      browserVersion: chrome, userAgent: uaFor(os, chrome),
      screen: rnd(SCREENS[os]), cores: rnd(CORES[os]), memory: rnd(RAM[os]),
      webglVendor: vendorFor(gpu), webglRenderer: gpu,
      locale, timezone: LOCALES[locale] || LOCALES["en-US"],
    };
  }
  ```
- **Mechanism**: A client-side randomized device generator already exists in the codebase. However, it is exclusively called during offline demo cloning (`App.jsx:595`) and was never wired into `newProfile()`.

### Root Cause 3: Hardcoded Attribute Reset on OS Switch
- **File**: `/home/gyoutu/src/persona-studio/dashboard/src/App.jsx`
- **Line**: `1223`
- **Implementation**:
  ```javascript
  const changeOS = (os) => set({
    os, userAgent: uaFor(os),
    screen: SCREENS[os][0],
    cores: CORES[os][1],
    memory: RAM[os][1],
    webglRenderer: GPUS[os][0],
    webglVendor: vendorFor(GPUS[os][0])
  });
  ```
- **Mechanism**: When a user selects a different OS in the editor drawer (e.g., macOS or Linux), the editor resets the profile to fixed index `[0]` and `[1]` of that target OS instead of sampling a fresh, coherent device.

### Root Cause 4: Backend Fallback Bypass in `create_profile`
- **File**: `/home/gyoutu/src/persona-studio/engine/persona/server.py`
- **Lines**: `738–751`
- **Implementation**:
  ```python
  @app.post("/api/profiles")
  def create_profile(profile: dict):
      profile.pop("_new", None)
      if not profile.get("engine"):
          profile["engine"] = engine_store.get_default_engine()
      full = to_dashboard_profile(to_engine_profile({**profile, "id": profile.get("id") or "new"}))
      full["folder"] = "Unfiled"
      profile = {**full, **{k: v for k, v in profile.items() if v is not None}}
      _remember_engine(profile)
      saved = dash.save(profile)
      return decorate(saved)
  ```
- **Mechanism**: The backend does contain a true random generator (`fingerprint.generate()` in `engine/persona/fingerprint.py:54`). However, `create_profile` merges incoming fields with `{**full, **{k: v for k, v in profile.items() if v is not None}}`. Because `newProfile()` populates all fields with static non-null values, the backend preserves the static frontend payload verbatim without calling `fingerprint.generate()`.

### Root Cause 5: Seed Omission and Canvas Noise Drift
- **File**: `/home/gyoutu/src/persona-studio/engine/persona/server.py`
- **Lines**: `328–361` (`to_dashboard_profile`)
- **Mechanism**:
  When converting an engine profile to a dashboard profile dictionary, `to_dashboard_profile` omits the `"seed"` attribute:
  ```python
  def to_dashboard_profile(prof: Profile) -> dict:
      fp = prof.fingerprint
      return {
          "name": prof.name,
          "os": OS_TO_DASH.get(fp.os, "Windows"),
          # ... screen, cores, memory, webglVendor, webglRenderer ...
          # MISSING: "seed": fp.seed
      }
  ```
  Consequently, `profiles.json` does not store `seed`. When `_materialise(d)` runs on browser launch (`server.py:886` -> `server.py:269`):
  `seed = int(d.get("seed") or 0) or generate(os=os_key).seed`
  Because `seed` is null in `profiles.json`, the backend generates a **brand-new random seed on every single launch**. This causes canvas and audio noise tables to mutate unpredictably, breaking session fingerprint stability.

---

## 3. Contrast Analysis: Working Randomization Paths

| Entry Point | Code Location | Randomization Status | Cause |
| :--- | :--- | :--- | :--- |
| **CLI Profile Creation** | `engine/persona/cli.py:80–93` | **Randomized & Coherent** | Explicitly calls `generate(os=args.os, locale=args.locale)`. |
| **Profile Duplication** | `engine/persona/server.py:1144–1158` | **Randomized & Coherent** | Calls `fp = generate(...)` and writes `"seed": fp.seed`. |
| **Bulk Batch API** | `engine/persona/bulk.py:100–120` | **Randomized & Coherent** | Iteratively invokes `fingerprint.generate(...)`. |
| **Bulk Modal UI** | `dashboard/src/App.jsx:2110–2132` | **Randomized if checked** | Uses `randomize ? rnd(arr) : dflt` across screens, cores, GPUs. |
| **Dashboard New Profile**| `dashboard/src/App.jsx:1130–1142` | **100% Static / Hardcoded** | Hardcodes static array indices `[0]` and `[1]`. |

---

## 4. Proposed Remediation Architecture

A robust fix must solve both **attribute randomization** (preventing fingerprint collisions) and **seed persistence** (guaranteeing cross-session stability).

```
                      ┌──────────────────────────────────────┐
                      │ User clicks "New profile" in Web UI  │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │  newProfile() calls freshDevice(os)  │
                      │  - Samples coherent GPU, RAM, Cores  │
                      │  - Samples Screen, UA, Locale        │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │  Editor Drawer renders unique device │
                      │  (changeOS also calls freshDevice)   │
                      └──────────────────┬───────────────────┘
                                         │
                                         ▼
                      ┌──────────────────────────────────────┐
                      │   Save Profile (POST /api/profiles)  │
                      └──────────────────┬───────────────────┘
                                         │
                    ┌────────────────────┴────────────────────┐
                    ▼                                         ▼
   ┌─────────────────────────────────┐       ┌─────────────────────────────────┐
   │ Backend: server.py              │       │ Backend: server.py              │
   │ to_dashboard_profile()          │       │ create_profile() & _materialise │
   │ Persists "seed": fp.seed        │       │ Respects & preserves "seed"     │
   └─────────────────────────────────┘       └─────────────────────────────────┘
```

### Component A: Frontend Random Device Initialization
1. In `dashboard/src/App.jsx:1130`, refactor `newProfile()` to delegate device properties to `freshDevice(os)`:
   ```javascript
   function newProfile(folder, defaultEngine = ENGINE_ORDER[0]) {
     const os = "Windows";
     const dev = freshDevice(os);
     return {
       id: nid(), name: "", folder: folder === "All profiles" ? "Facebook Ads" : folder,
       status: "stopped", os, tags: [], engine: defaultEngine, browser: "Chrome",
       ...dev,
       canvas: "Noise", webrtc: "Altered", audio: "Noise", fonts: "Masked",
       geo: "Prompt", mediaVideo: 1, mediaAudio: 1, dnt: false, proxy: null,
       notes: "", startupUrls: "", extensions: "", lastActive: "never", _new: true,
     };
   }
   ```
2. In `dashboard/src/App.jsx:1223`, update `changeOS(os)`:
   ```javascript
   const changeOS = (os) => {
     const dev = freshDevice(os, p.locale);
     set({ os, ...dev });
   };
   ```

### Component B: Backend Seed Persistence
1. In `engine/persona/server.py:348` (`to_dashboard_profile`), include the noise seed:
   ```python
   def to_dashboard_profile(prof: Profile) -> dict:
       fp = prof.fingerprint
       return {
           # ... existing fields ...
           "webglTable": fp.webgl or {},
           "seed": fp.seed,  # Persist deterministic noise seed to dashboard JSON
           # ... remaining fields ...
       }
   ```
2. In `engine/persona/server.py:748` (`create_profile`), ensure a newly generated seed is retained when `to_engine_profile` runs.

---

## 5. Architectural Tradeoffs & Design Decisions

### Why a Hybrid (Frontend Init + Backend Seed) approach?
1. **Immediate Visual Feedback in UI**:
   - The user opens the "New profile" drawer *before* saving. If randomization only occurred on the backend upon save, the user would see a static preview in the UI, and saving would alter the fingerprint behind their back.
   - Calling `freshDevice()` in `newProfile()` allows the operator to inspect the specific randomized hardware profile (e.g., Core count, GPU model, Screen size) before committing.
2. **Coherence Preservation**:
   - `freshDevice()` pairs the `webglVendor` with `vendorFor(gpu)` and limits choices to `GPUS[os]`, `SCREENS[os]`, and `CORES[os]`. This guarantees 100% fingerprint coherence (passing `coherence(p)` validation).
3. **Cross-Session Stability**:
   - Persisting `seed` in `to_dashboard_profile` closes the leak where canvas/audio noise tables were re-rolled on every browser launch. A profile must have a distinct fingerprint from others, but must remain identical to itself across multiple runs.

---

## 6. Verification Criteria

1. **Dashboard Randomness Check**: Click "New profile" 5 times sequentially; verify that `screen`, `cores`, `memory`, and `webglRenderer` vary across profiles.
2. **Collision Test**: Confirm that newly created profiles do not share an `fpSignature` or trigger `/api/profiles/collisions`.
3. **Cross-Session Seed Invariant**: Verify that launching a profile, shutting it down, and relaunching it preserves the exact same `seed` in `engine_store` and identical canvas hash in the live browser.
