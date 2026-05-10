# reBotArm Daemon — 重力補償チューニング状態

`configs/rebotarm_daemon.yaml` の `gravity_comp` ブロックの**現在値とその根拠**、および次に触るべきレバーをまとめる。実装は `controllers.py:GravityCompController`。

GRAVITY_COMP モードでアームが受け取る MIT トルクは

```
τ = τ_g(q) + friction_tau · sign(q̇) · taper(q̇) · 𝟙{|q̇|>deadband} − kd · q̇
```

各項の役割と現在値:

| 項 | 役割 | 現在値 (joint1..6) |
|---|---|---|
| `τ_g(q)` | Pinocchio 重力補償（静的） | `gravity_in_base: [-6.937, 0.0, -6.937]` (右 45° 傾斜マウント) |
| `kp` | 位置剛性。GRAVITY_COMP では 0 固定（自由に back-drive させる） | `[0, 0, 0, 0, 0, 0]` |
| `kd` | 速度ダンピング。手放し後の減衰を担う | `[0.6, 0.6, 0.8, 0.6, 0.5, 0.0]` |
| `friction_tau_nm` | Coulomb 摩擦補償。stiction を打ち消して初動を軽くする | `[0.9, 0.3, 0.85, 0.2, 0.2, 0.0]` |
| `vel_deadband_rad_s` | sign(q̇) chatter 防止。この内側では摩擦補償をオフ | `[0.05, 0.05, 0.075, 0.075, 0.075, 0.02]` |
| `friction_vel_taper_rad_s` | 摩擦補償の速度フェード。`|q̇| → v_taper` で 0 に減衰 | `[1.5, 1.5, 1.5, 1.0, 1.0, 0.0]` |

## 根拠

**proximal (joint1-3, 4340P)** は反射慣性が大きく、放置すると一番「飛ぶ」。`kd` を distal より高め、`friction_tau` も大きめ、`v_taper` も大きめ (1.5 rad/s) で「初動軽め・終端をしっかり殺す」非対称特性に振っている。

**distal (joint4-5, 4310)** は減速比が低く stiction も小さい。`friction_tau` は控えめ、`v_taper` も 1.0 rad/s で十分。

**joint6** は `friction_tau=0` 固定（補償不要なくらい軽い）。`v_taper=0` だが `friction_tau=0` なので無関係。

`friction_vel_taper_rad_s` 導入前は friction comp が速度に依らず一定で、手放し後に「friction が damping に勝ち続ける」runaway が発生し、joint1 で q̇ が `friction_tau / kd ≈ 1.5 rad/s` に張り付いて止まらない症状があった。タイパーで `q̇ → v_taper` で comp を 0 に落とし、純 viscous で減速する領域を作って構造的に殺している。

## チューニングのレバー

| 症状 | まず触る | 次に触る |
|---|---|---|
| 動き出しが重い | `friction_tau_nm` を joint 別に +0.1 ずつ | `vel_deadband_rad_s` を下げる |
| 手放し後に飛ぶ・止まりにくい | `friction_vel_taper_rad_s` を下げる (例 1.5 → 1.0) | `kd` を +0.1〜0.2 |
| 静止時に微振動 | `vel_deadband_rad_s` を上げる | `kd` を下げる |
| 静止時にゆっくりドリフト | （未実装）stationary hold ／ ペイロード補償 | `friction_tau_nm` を僅かに下げる |

`friction_vel_taper_rad_s` は **初動感を保ったまま終端だけを殺せる唯一のレバー**なので、装着 vs 床置きで「止まらない」差が出たときの第一選択。

## 既知の課題

- **床置きと装着でひと組のパラメータがベストにならない**: 物理が違う（装着は基底加速度・体軸傾きが外乱として乗る）。現状はプロファイル切替が未実装で、装着寄りの値で妥協。
- **IMU 未活用**: ハードは装着済みだが daemon から読めていない。装着時に `gravity_in_base` を動的更新できれば構造的に解決できる外乱の半分以上が消えるはず。
- **ペイロード未補償**: replay/teleop で重い物を掴むと `Δp ≈ payload_torque / position.kp` の定常偏差が残る。GRAVITY_COMP では「物を持たせると重い方向にゆっくり流れる」として現れる。

優先度の議論は会話ログ参照（`(1) v_taper → (2) profile → IMU 開通 → (5) base IMU comp → (3) stationary hold → (4) payload`）。
