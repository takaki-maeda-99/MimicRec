[MimicRec Quest連携](README.md)

# Ubuntu 22.04からMeta QuestへUnityアプリをビルドする

このページは、Ubuntu 22.04上で本リポジトリを開き、Meta QuestへAPKをビルド・転送・起動するまでの手順をまとめたものです。

確認済みの構成は以下です。

- Ubuntu 22.04
- Unity Editor 6000.2.15f1
- Meta XR Core SDK 85.0.0
- Unity OpenXR Plugin 1.16.1
- Meta Quest 3S
- Android Build Support、SDK/NDK、OpenJDKはUnity Hubから導入

## 1. Unityプロジェクトを開く

プロジェクトのパスは次のとおりです。

```text
/path/to/MimicRec/third_party/unity_ros_teleoperation
```

Unity Hubから、プロジェクトで指定されているUnity 6000.2.15f1を使って開きます。別バージョンへ自動更新しないでください。

## 2. Meta XR SDKのLinuxコンパイルエラーを直す

Meta XR Core SDK 85.0.0では、Linux Editor上で次のエラーが発生する場合があります。

```text
Library/PackageCache/com.meta.xr.sdk.core@f8b4cfb2789f/
Editor/MetaXRSimulator/Installer.cs(88,42):
error CS0103: The name 'downloadedInstallerPath' does not exist in the current context
```

原因は、`downloadedInstallerPath` がWindows/macOS向けプリプロセッサ分岐の中でしか宣言されていないことです。

対象メソッドでは、変数を分岐前で宣言し、Windows/macOS以外ではダウンロード前に失敗を返します。

```csharp
string downloadedInstallerPath;
#if UNITY_EDITOR_WIN
downloadedInstallerPath =
    Path.Combine(XRSimConstants.DownloadFolderPath, $"meta_xr_simulator.msi");
#elif UNITY_EDITOR_OSX
downloadedInstallerPath =
    Path.Combine(XRSimConstants.DownloadFolderPath, $"meta_xr_simulator.dmg");
#else
onError?.Invoke(
    "Meta XR Simulator installer is only supported on Windows and macOS.");
return false;
#endif
```

上記はメソッド先頭の差し替え部分だけです。`#endif`より後にある既存のダウンロード処理、`try`ブロック、メソッド末尾は削除しません。

この変更により、LinuxではMeta XR Simulatorのダウンロードを安全にスキップし、Windows/macOSの動作は維持されます。

### 注意: PackageCacheの変更は一時的

このファイルは`Library/PackageCache`内にあり、Git管理対象外です。`Library`の削除、パッケージ再解決、SDK更新で変更が失われる可能性があります。

恒久対応の候補は次のとおりです。

- この問題が修正されたMeta XR Core SDKへ更新する
- Meta XR Core SDKを埋め込みパッケージ化して管理する
- 同じ修正を再適用するパッチを保管する

ただし、SDK全体の埋め込みは容量が大きいため、このリポジトリではパッケージ更新時に修正状況を確認する運用が現実的です。

手動編集で括弧や`try`ブロックを壊した場合は、同じ85.0.0の正規パッケージから`Installer.cs`を復元してから、上記の最小変更だけを適用してください。

## 3. Android Build Supportをインストールする

次のダイアログが出る場合、Android SDKのパス設定ではなく、UnityのAndroidモジュール自体が不足している可能性があります。

```text
Android SDK not found
```

Unity Hubで次のモジュールをUnity 6000.2.15f1へ追加します。

- Android Build Support
- Android SDK & NDK Tools
- OpenJDK

Unity HubのGUIでは、`Installs`から6000.2.15f1の設定メニューを開き、`Add modules`を選択します。

旧Unity Hub headless CLIを使う場合は、次のコマンドでも追加できます。現在このCLIは非推奨なので、通常はGUIを使用してください。

```bash
unityhub -- --headless install-modules \
  --version 6000.2.15f1 \
  --module android \
  --childModules
```

インストール後、次のディレクトリが存在することを確認します。

```text
~/Unity/Hub/Editor/6000.2.15f1/Editor/Data/PlaybackEngines/AndroidPlayer/
├── SDK
├── NDK
└── OpenJDK
```

本環境では、SDK Platform 34/35/36、Build Tools 36.0.0、NDK r27c、OpenJDK 17.0.9が導入されました。

## 4. Questの開発者モードを有効にする

1. Meta開発者アカウントとOrganizationを用意します。
2. Meta Horizonアプリで対象のQuestを選択します。
3. Headset SettingsのDeveloper Modeを有効にします。
4. データ通信対応のUSB-CケーブルでQuestとUbuntu PCを接続します。
5. Questを被り、`USBデバッグを許可`を選択します。
6. 可能なら`このコンピューターを常に許可`も有効にします。

## 5. UbuntuからQuestをADB認識させる

Unity同梱ADBを変数へ設定します。

```bash
QUEST_ADB="$HOME/Unity/Hub/Editor/6000.2.15f1/Editor/Data/PlaybackEngines/AndroidPlayer/SDK/platform-tools/adb"
```

接続状態を確認します。

```bash
"$QUEST_ADB" devices -l
```

正常な例:

```text
List of devices attached
<QUEST_SERIAL>  device usb:1-4.2 product:panther model:Quest_3S device:panther
```

状態ごとの意味は次のとおりです。

- `device`: 使用可能
- `unauthorized`: Quest内でUSBデバッグを許可する
- 一覧が空: USBケーブル、開発者モード、udev権限を確認する

### Questは`lsusb`に出るがADBに出ない場合

USB認識を確認します。

```bash
lsusb
```

Quest 3Sでは次のように表示されます。

```text
ID 2833:5013 Oculus VR, Inc. Quest 3S
```

`lsusb`には出るのにADB一覧が空の場合、Meta/Oculus用udevルールを追加します。

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2833", MODE="0660", GROUP="plugdev", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/51-oculus.rules
```

ルールを再読み込みします。

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change --subsystem-match=usb --attr-match=idVendor=2833
```

ユーザーが`plugdev`に所属していることも確認します。

```bash
id
```

所属していない場合は追加し、ログアウト・ログインします。

```bash
sudo usermod -aG plugdev "$USER"
```

その後、QuestをUSBから一度抜いて再接続し、ADBを再起動します。

```bash
"$QUEST_ADB" kill-server
"$QUEST_ADB" devices -l
```

## 6. UnityのQuest Build Profileを使う

このプロジェクトには`Assets/Settings/Build Profiles/Quest.asset`が用意されています。

1. Unityで`File > Build Profiles`を開きます。
2. `Quest`プロファイルを選択します。
3. `Switch Profile`を押します。
4. プロファイルに`Active`と表示されたことを確認します。
5. `Run Device`で接続したQuestを選択します。

Questプロファイルの主な設定は次のとおりです。

- Scene: `Assets/Scenes/Main.unity`
- Application ID: `com.RSL.teleoperation`
- APKビルド（App Bundleではない）
- IL2CPP
- ARM64
- Minimum API Level 30
- Target API Level 34
- OpenXR/Meta Quest loader有効

## 7. ビルド前に出る警告へ対応する

### Unsupported Input Handling

```text
PlayerSettings > Active Input Handling is set to Both
```

Androidでは`Both`が非対応です。ダイアログでは`No`を選び、次を変更します。

1. `Edit > Project Settings > Player`
2. `Other Settings > Configuration`
3. `Active Input Handling`
4. `Input System Package (New)`を選択
5. Unityの再起動要求を受け入れる

本プロジェクトはInput SystemとXR Interaction Toolkitを使用するため、`Input System Package (New)`を選択します。

### Can not sign the application

```text
Unable to sign the application; please provide passwords!
```

ローカルのQuestで動作確認するだけなら、カスタムKeystoreは不要です。

1. `Edit > Project Settings > Player`
2. Androidタブの`Publishing Settings`を開く
3. `Custom Keystore`または`Use Custom Keystore`を無効にする

Unityのデバッグ用Keystoreで署名されます。Meta Horizon StoreやRelease Channelへ配布する場合は、チームで管理している正式なKeystoreを使用してください。KeystoreのパスワードをGitへ保存してはいけません。

## 8. Build and Runする

Quest Build Profileで`Build and Run`を押すと、APKの保存ダイアログが開きます。これは正常です。

例えば次の場所へ保存します。

```text
Builds/Quest/teleoperation.apk
```

初回はIL2CPPコンパイルがあるため、数分以上かかる場合があります。成功すると、UnityがAPKをQuestへインストールし、そのままアプリを起動します。

APKのみを作った場合は、手動インストールもできます。

```bash
"$QUEST_ADB" install -r Builds/Quest/teleoperation.apk
```

## 9. 2回目以降はQuest単体で起動する

毎回PCから起動する必要はありません。

1. QuestのMetaボタンでユニバーサルメニューを開く
2. アプリライブラリを開く
3. フィルターから`提供元不明`または`Unknown Sources`を選択
4. `teleoperation`を起動する

`Build and Run`が必要なのは、Unity側の変更を新しいAPKとして再ビルド・更新するときです。

PCから明示的に再起動する場合は次を使えます。

```bash
"$QUEST_ADB" shell am start -W \
  -n com.RSL.teleoperation/com.unity3d.player.UnityPlayerActivity
```

## 10. 一瞬表示されて消える場合

まず、プロセスが動いているか確認します。

```bash
"$QUEST_ADB" shell pidof com.RSL.teleoperation
```

PIDが表示されれば、アプリは動作中です。Questのアプリライブラリまたは最近使ったアプリから前面へ戻します。

起動し直す場合:

```bash
"$QUEST_ADB" shell am start -W \
  -n com.RSL.teleoperation/com.unity3d.player.UnityPlayerActivity
```

Unityログを確認する場合:

```bash
APP_PID=$("$QUEST_ADB" shell pidof com.RSL.teleoperation)
"$QUEST_ADB" logcat --pid="$APP_PID" -v time
```

インストール済みパッケージの情報は次で確認できます。

```bash
"$QUEST_ADB" shell dumpsys package com.RSL.teleoperation
```

## 11. ROS 2へ接続する

Quest上の`localhost`はQuest自身を指します。ROS TCP EndpointがUbuntu PCまたはロボット上で動いている場合、接続先を`localhost`にしてはいけません。

### ROS TCP Endpointをビルドする

MimicRecでは`ROS-TCP-Endpoint`を`main-ros2`の固定submoduleとして管理し、専用ブリッジと同じColconワークスペースへ構築します。

```bash
cd /path/to/MimicRec
git submodule update --init --recursive
bash scripts/setup_quest_ros2.sh
```

手動で別ワークスペースを作る場合は、[leggedrobotics/ROS-TCP-Endpoint](https://github.com/leggedrobotics/ROS-TCP-Endpoint/tree/main-ros2)の`main-ros2`ブランチをColconワークスペースへ追加します。Ubuntu 22.04とROS 2 Humbleの例は次のとおりです。

```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
git clone --branch main-ros2 \
  https://github.com/leggedrobotics/ROS-TCP-Endpoint.git

cd ~/ros2_ws
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src --recursive --yes
colcon build --symlink-install
source install/setup.bash
```

既に別のROS 2ワークスペースを使っている場合は、そのワークスペースの`src`へcloneしてください。

リポジトリを`~/ROS-TCP-Endpoint`へ直接cloneし、そのディレクトリで`colcon build`した場合は、以降の`source ~/ros2_ws/install/setup.bash`を次へ読み替えます。

```bash
source ~/ROS-TCP-Endpoint/install/setup.bash
```

### `colcon build`でCMake 3.5互換エラーが出る場合

次のエラーは、ROS 2用ではなくROS 1用の`main`ブランチをビルドしているときに発生します。

```text
Compatibility with CMake < 3.5 has been removed from CMake.
```

現在のブランチを確認します。

```bash
git branch --show-current
```

`main`と表示された場合、CMakeオプションで回避せず、ROS 2用の`main-ros2`へ切り替えます。

```bash
git fetch origin
git switch main-ros2
```

誤ったブランチで生成された`build`、`install`、`log`がある場合は、削除する代わりに別名で退避してから再ビルドできます。

```bash
mv build build.ros1-failed
mv install install.ros1-failed
mv log log.ros1-failed
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

切替後の`package.xml`には`ament_python`、ROS 1版には`catkin`と`rospy`が記載されています。

### `error: option --editable not recognized`が出る場合

Ubuntu標準のColconと、`~/.local`へ入った新しい`setuptools`が競合している可能性があります。バージョンと読込元を確認します。

```bash
python3 -c \
  'import setuptools; print(setuptools.__version__); print(setuptools.__file__)'
```

`~/.local/lib/python3.10/site-packages`の`setuptools`が表示された場合は、ユーザー領域のPythonパッケージを今回のビルドだけ無効にします。

```bash
source /opt/ros/humble/setup.bash
PYTHONNOUSERSITE=1 colcon build --symlink-install
source install/setup.bash
```

ユーザー領域の`setuptools`をアンインストールする必要はありません。本環境では`setuptools 80.9.0`で失敗し、Ubuntu 22.04標準の`59.6.0`を使うことでビルドに成功しました。

### Endpointを起動する

通常はMimicRecのEndpointとQuestブリッジをまとめて起動します。

```bash
cd /path/to/MimicRec
bash scripts/run_quest_ros2.sh
```

Endpointだけを手動起動する場合は、ROS 2を使うターミナルごとに環境を読み込み、TCPポート`10000`で待ち受けます。

```bash
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 run ros_tcp_endpoint default_server_endpoint --ros-args \
  -p ROS_IP:=0.0.0.0 \
  -p ROS_TCP_PORT:=10000
```

`0.0.0.0`は全ネットワークインターフェースで待ち受ける指定です。Questへ入力するアドレスには使いません。

PCのIPv4アドレスを確認します。

```bash
hostname -I
```

複数表示される場合は、Questと同じWi-FiまたはLANに属するアドレスを選びます。例えばPCが`192.168.1.20`なら、Questへ設定するIPも`192.168.1.20`です。

UFWが有効な場合は、必要に応じてTCPポートを許可します。

```bash
sudo ufw allow 10000/tcp
```

### Questアプリの接続先を設定する

QuestとROS TCP Endpointを同じネットワークへ接続し、アプリ内のPalm Menuから次を設定します。

- IP: ROS TCP Endpointが動作しているPC/ロボットのIPv4アドレス
- Port: `10000`

Palm Menuプレハブに保存されている初期値は`localhost:10000`です。Questでは`localhost`のまま接続できないため、必ず上で確認したPC/ロボットのIPv4アドレスへ変更します。アプリ内で変更した値はPlayerPrefsへ保存され、次回起動にも引き継がれます。

フォーク版ROS TCP Connectorは、EndpointとのハンドシェイクでROS 1/ROS 2を自動判別します。Unity側でROS 2モードを別途選ぶ必要はありません。接続に成功すると、Palm MenuのROSステータスが緑になります。

## 12. コントローラ姿勢のPublishを確認する

Mainシーンには`HeadsetPublisher`が組み込み済みで、新しいUnityスクリプトを追加しなくても次のデータをPublishします。

| ROSトピック | 型 | 内容 |
| --- | --- | --- |
| `/tf` | `tf2_msgs/msg/TFMessage` | `vr_origin`を親とするヘッドセット・左右コントローラの姿勢 |
| `/quest/pose/headset` | `geometry_msgs/msg/PoseStamped` | ヘッドセット姿勢 |

`/tf`内で使用する子フレームは次のとおりです。

- ヘッドセット: `headset`
- 左コントローラ: `hand_left`
- 右コントローラ: `hand_right`

別ターミナルでROS 2環境を読み込み、トピックを確認します。

```bash
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 topic list
ros2 topic type /tf
ros2 topic echo /tf --once
```

コントローラを動かしながら特定フレームの変化を見る場合は、次のどちらかを実行します。コマンドは停止するまで表示を続けるため、もう片方を見るときは`Ctrl+C`で止めます。

```bash
ros2 run tf2_ros tf2_echo vr_origin hand_left
ros2 run tf2_ros tf2_echo vr_origin hand_right
```

Unity座標は`ROSGeometry.To<FLU>()`でROSのFLU座標系へ変換されます。コントローラについては、xが前、yが下、zが右になるよう定義されています。

左右コントローラの個別`PoseStamped`トピックは、現状の`HeadsetPublisher`からはPublishされません。受信側では通常`/tf`を利用します。`/quest/pose/left`と`/quest/pose/right`のような個別トピックが必要な場合は、Unity側のPublisher追加が別途必要です。

## 13. 最終チェックリスト

- [ ] Unity Editorが6000.2.15f1
- [ ] ConsoleにC#コンパイルエラーがない
- [ ] Android Build Support、SDK/NDK、OpenJDKが導入済み
- [ ] QuestのDeveloper Modeが有効
- [ ] `adb devices -l`で状態が`device`
- [ ] Quest Build ProfileがActive
- [ ] Active Input Handlingが`Input System Package (New)`
- [ ] ローカル開発時はCustom Keystoreが無効
- [ ] `Builds/Quest/teleoperation.apk`が生成される
- [ ] QuestのUnknown Sourcesから`teleoperation`を再起動できる
- [ ] ROS接続先が`localhost`ではなくROS TCP EndpointのIP
- [ ] `ros2 topic echo /tf --once`で`hand_left`と`hand_right`を確認できる
