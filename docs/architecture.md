# MimicRec System Architecture

```mermaid
flowchart LR
    subgraph Browser["Browser :5173"]
        UI["React 19 + Vite<br/>Pages: Record / Replay / Episodes / Datasets / Inference / Settings"]
        APIc["api/client.ts<br/>(REST, TanStack Query)"]
        WSc["api/ws.ts<br/>(WebSocket)"]
        Store["Zustand stores<br/>(session / record-form / inference)"]
        UI --> APIc
        UI --> WSc
        UI --> Store
    end

    subgraph Backend["FastAPI :8000 (Python 3.12, asyncio)"]
        REST["api/routes<br/>session · replay · datasets · episode · configs · settings · inference"]
        WS["WebSocket<br/>(telemetry / preview frames / inference_hub)"]

        subgraph Session["session/"]
            SM["SessionManager<br/>(lifecycle.py, state.py)"]
            CL["control_loop.py"]
            DISP["dispatcher.py"]
            RPL["replay.py + replay_safety.py"]
        end

        subgraph Inference["inference/"]
            CONTRACT["contract.py<br/>(YAML → ContractSpec)"]
            CLIENT["client.py<br/>(httpx, JPEG)"]
            PROD["producer.py<br/>(deadlock-safe re-arm)"]
            BUF["chunk_buffer.py<br/>(half-prefetch + flush)"]
            DEC["action_decoder.py<br/>(ee_delta + IK chain)"]
            SAF["safety.py<br/>(clamp / joint limit / slow-stop)"]
            ICL["control_loop.py"]
        end

        subgraph Kinematics["kinematics/"]
            FK["fk.py (FKService)"]
            IK["ik.py (IKService)"]
        end

        subgraph Adapters["adapters/"]
            ROBOT["Robot adapters<br/>so101 · rebotarm_zmq · sim_bridge · mock_robot"]
            TELE["Teleop adapters<br/>so_leader · web_teleop · mock_teleop · sim_bridge"]
        end

        subgraph Cameras["cameras/"]
            CAM["manager · opencv · sim · mock · preview · recording"]
        end

        subgraph Recording["recording/"]
            PEND["pending.py<br/>(per-episode buffer + mp4 writer)"]
            WRITER["writer.py · parquet_row.py"]
            META["metadata.py · dataset_layout.py"]
        end

        ANNO["annotator/subtask.py<br/>(Gemma VLM, calls MimicAnno)"]

        REST --> SM
        WS --> SM
        SM --> CL
        SM --> DISP
        SM --> ICL
        SM --> PROD
        CL --> ROBOT
        CL --> TELE
        CL --> CAM
        CL --> PEND
        ICL --> SAF
        ICL --> BUF
        ICL --> CAM
        ICL --> PEND
        SAF --> DISP
        PROD --> CLIENT
        PROD --> DEC
        PROD --> BUF
        DEC --> IK
        DEC --> FK
        DISP --> RPL
        RPL --> ROBOT
        PEND --> WRITER
        WRITER --> META
        REST --> ANNO
        REST --> META
    end

    VLAS["VLA Server (separate process)<br/>e.g. Gemma-VLA on :8001"]
    CLIENT -->|HTTP /predict| VLAS

    subgraph Storage["datasets/&lt;name&gt;/ (LeRobot v3.0)"]
        DATA["data/chunk-NNN/episode_NNNNNN.parquet"]
        VIDEO["videos/observation.images.&lt;cam&gt;/chunk-NNN/*.mp4"]
        METAJ["meta/info.json · episodes.jsonl · tasks.parquet"]
    end

    subgraph External["External"]
        HW["Hardware<br/>SO-101 · SO Leader (Feetech)<br/>reBot Arm B601-DM (ZMQ daemon)<br/>USB cameras /dev/video*"]
        SIM["Isaac Sim 5.0<br/>(ZMQ bridge)"]
        MA["MimicAnno/<br/>(VLM annotation pipeline)"]
    end

    APIc -->|HTTP| REST
    WSc -->|WS| WS
    ROBOT --> HW
    TELE --> HW
    ROBOT --> SIM
    TELE --> SIM
    CAM --> HW
    WRITER --> DATA
    PEND --> VIDEO
    META --> METAJ
    ANNO --> MA
    REST -->|"GET /datasets/{ds}/episodes/{idx}/video/{cam}"| VIDEO
    REST -->|"GET .../frames"| DATA
```

## Notes

- Frontend (`frontend/src/`) talks to FastAPI on `:8000` via REST + WebSocket.
- `SessionManager` is the hub. `control_loop` drives adapters + cameras + the recording buffer; `dispatcher` / `replay` handles playback.
- Adapters split into robot (so101 / rebotarm_zmq / sim_bridge / mock) and teleop (so_leader / web_teleop / sim_bridge / mock).
- Recording: `pending` buffers per episode, then `writer` + `parquet_row` emit parquet on commit; `metadata` / `dataset_layout` update meta files.
- Storage follows LeRobot v3: `data/`, `videos/{video_key}/chunk-NNN/`, `meta/`.
- Subtask annotation lives in the `MimicAnno/` sub-project.

### Inference mode (`SessionMode.INFERENCE`)

`SessionManager` also supports a third mode where the action source is an external Vision-Language-Action (VLA) HTTP server instead of a teleoperator. `inference/producer.py` runs as an async task: it snapshots cameras + robot state + instruction, calls the VLA server, decodes the response into joint targets via FK/IK, and pushes them to `chunk_buffer`. `inference/control_loop.py` consumes one step per tick, runs it through `inference/safety.py` (per-step delta clamp + joint limit + slow-stop on chunk-late + gripper hold), and writes to the same `command_goal_slot` as teleop. `RECORDING` phase reuses the existing parquet/mp4 writer — rollouts are normal LeRobot v3 episodes with three additional metadata columns (`source`, `inference_config`, `stop_reason`). Telemetry events stream to a new `inference_hub` WebSocket. Contracts are YAML files at `configs/inference/<name>.yaml`, validated by `inference/contract.py` (pydantic v2). See spec `docs/superpowers/specs/2026-05-05-vla-inference-interface-design.md` for the full design.
