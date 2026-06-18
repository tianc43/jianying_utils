import { useEffect, useState } from "react";
import { useAtom, useAtomValue, useSetAtom } from "jotai";
import { open } from "@tauri-apps/plugin-dialog";
import { listen } from "@tauri-apps/api/event";
import {
  Alert,
  Badge,
  Box,
  Button,
  Checkbox,
  Code,
  Container,
  Divider,
  Group,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { CheckCircle2, ClipboardList, Download, FolderOpen, Info, LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import {
  appendLogAtom,
  canInstallAtom,
  clearRunStateAtom,
  currentStepAtom,
  draftNameAtom,
  draftsDirAtom,
  installingAtom,
  logsAtom,
  overwriteAtom,
  placeholderIdAtom,
  resultAtom,
  setCurrentStepAtom,
  sourceAtom,
  sourceModeAtom,
} from "./state";
import { getDiagnosticsInfo, getEnvironmentInfo, installDraft, InstallLogEvent, openLogDir } from "./tauri";

export default function App() {
  const [diagnosticsText, setDiagnosticsText] = useState("");
  const [source, setSource] = useAtom(sourceAtom);
  const [sourceMode, setSourceMode] = useAtom(sourceModeAtom);
  const [draftsDir, setDraftsDir] = useAtom(draftsDirAtom);
  const [draftName, setDraftName] = useAtom(draftNameAtom);
  const [placeholderId, setPlaceholderId] = useAtom(placeholderIdAtom);
  const [overwrite, setOverwrite] = useAtom(overwriteAtom);
  const [installing, setInstalling] = useAtom(installingAtom);
  const result = useAtomValue(resultAtom);
  const logs = useAtomValue(logsAtom);
  const currentStep = useAtomValue(currentStepAtom);
  const canInstall = useAtomValue(canInstallAtom);
  const appendLog = useSetAtom(appendLogAtom);
  const clearRunState = useSetAtom(clearRunStateAtom);
  const setCurrentStep = useSetAtom(setCurrentStepAtom);
  const setResult = useSetAtom(resultAtom);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    listen<InstallLogEvent>("install-log", (event) => {
      appendLog({ level: event.payload.level, message: event.payload.message });
      setCurrentStep({
        key: event.payload.step,
        level: event.payload.level,
        message: event.payload.message,
      });
    }).then((handler) => {
      unlisten = handler;
    });
    return () => {
      unlisten?.();
    };
  }, [appendLog, setCurrentStep]);

  useEffect(() => {
    getEnvironmentInfo()
      .then((info) => {
        if (info.defaultDraftsDir) {
          setDraftsDir(info.defaultDraftsDir);
          appendLog({ level: "info", message: `已识别剪映草稿目录：${info.defaultDraftsDir}` });
        }
        if (info.detectedPlaceholderId) {
          appendLog({ level: "success", message: `已识别本机占位符：${info.detectedPlaceholderId}` });
        }
      })
      .catch((error) => {
        appendLog({ level: "error", message: `环境检测失败：${String(error)}` });
      });
  }, [appendLog, setDraftsDir]);

  useEffect(() => {
    getDiagnosticsInfo()
      .then((info) => {
        setDiagnosticsText(`jy-downloader\n日志目录：${info.logDir}\n日志文件：${info.logFile}`);
      })
      .catch(() => {
        setDiagnosticsText("jy-downloader\n日志信息暂不可用");
      });
  }, []);

  async function chooseDraftsDir() {
    const selected = await open({ directory: true, multiple: false, title: "选择剪映草稿目录" });
    if (typeof selected === "string") {
      setDraftsDir(selected);
    }
  }

  async function chooseSourceZip() {
    const selected = await open({
      directory: false,
      multiple: false,
      title: "选择草稿 ZIP",
      filters: [{ name: "ZIP", extensions: ["zip"] }],
    });
    if (typeof selected === "string") {
      setSource(selected);
    }
  }

  function changeSourceMode(value: string) {
    setSourceMode(value === "file" ? "file" : "url");
    setSource("");
  }

  async function onInstall() {
    clearRunState();
    setInstalling(true);
    try {
      const installResult = await installDraft({
        source: source.trim(),
        draftsDir: draftsDir.trim(),
        draftName: draftName.trim() || undefined,
        placeholderId: placeholderId.trim() || undefined,
        overwrite,
      });
      setResult(installResult);
      appendLog({ level: "success", message: `导入完成：${installResult.targetDir}` });
    } catch (error) {
      appendLog({ level: "error", message: String(error) });
      setCurrentStep({ key: "error", level: "error", message: String(error) });
    } finally {
      setInstalling(false);
    }
  }

  async function onOpenLogDir() {
    try {
      await openLogDir();
    } catch (error) {
      appendLog({ level: "error", message: `打开日志目录失败：${String(error)}` });
    }
  }

  async function onCopyDiagnostics() {
    try {
      await navigator.clipboard.writeText(diagnosticsText);
      appendLog({ level: "success", message: "诊断信息已复制。" });
    } catch (error) {
      appendLog({ level: "error", message: `复制诊断信息失败：${String(error)}` });
    }
  }

  return (
    <Box className="app-shell">
      <Container size="lg" py="xl">
        <Group justify="space-between" align="flex-end" mb="lg">
          <div>
            <Group gap="sm" mb={6}>
              <Title order={1}>jy-downloader</Title>
              <Badge variant="filled" color="teal">Preview</Badge>
            </Group>
            <Text c="dimmed" size="sm">下载服务端便携草稿包，并在本机转换成剪映可识别的草稿。</Text>
          </div>
          <Tooltip label="重置本次导入日志和结果">
            <Button variant="subtle" leftSection={<RotateCcw size={16} />} onClick={clearRunState}>
              清空
            </Button>
          </Tooltip>
        </Group>

        <div className="workspace">
          <Paper withBorder radius="sm" p="lg" className="panel">
            <Stack gap="md">
              <Title order={2}>导入参数</Title>
              <SegmentedControl
                value={sourceMode}
                onChange={changeSourceMode}
                data={[
                  { label: "下载 URL", value: "url" },
                  { label: "本地 ZIP", value: "file" },
                ]}
                fullWidth
              />
              <TextInput
                label={sourceMode === "url" ? "草稿下载 URL" : "草稿 ZIP 文件"}
                placeholder={sourceMode === "url" ? "http://server/drafts/<draft_id>/download" : "D:\\drafts\\example.zip"}
                value={source}
                onChange={(event) => setSource(event.currentTarget.value)}
                leftSection={<Download size={16} />}
                error={
                  source.trim().length === 0
                    ? undefined
                    : sourceMode === "url" && !source.trim().startsWith("http://") && !source.trim().startsWith("https://")
                      ? "请输入 http:// 或 https:// 开头的下载地址"
                      : sourceMode === "file" && !source.trim().toLowerCase().endsWith(".zip")
                        ? "请选择 .zip 草稿包"
                        : undefined
                }
                rightSection={
                  sourceMode === "file" ? (
                    <Tooltip label="选择 ZIP">
                      <button className="icon-button" onClick={chooseSourceZip} type="button">
                        <FolderOpen size={16} />
                      </button>
                    </Tooltip>
                  ) : undefined
                }
              />
              <TextInput
                label="剪映草稿目录"
                placeholder="D:\\jianying\\JianyingPro Drafts"
                value={draftsDir}
                onChange={(event) => setDraftsDir(event.currentTarget.value)}
                rightSection={
                  <Tooltip label="选择目录">
                    <button className="icon-button" onClick={chooseDraftsDir} type="button">
                      <FolderOpen size={16} />
                    </button>
                  </Tooltip>
                }
              />
              <TextInput
                label="导入后的草稿名"
                placeholder="留空则使用草稿包内名称"
                value={draftName}
                onChange={(event) => setDraftName(event.currentTarget.value)}
              />
              <TextInput
                label="占位符 ID"
                placeholder="留空则自动扫描本机剪映草稿"
                value={placeholderId}
                onChange={(event) => setPlaceholderId(event.currentTarget.value)}
              />
              <Checkbox
                label="覆盖同名草稿目录"
                checked={overwrite}
                onChange={(event) => setOverwrite(event.currentTarget.checked)}
              />
              <Button
                leftSection={installing ? <LoaderCircle className="spin" size={16} /> : <Download size={16} />}
                disabled={!canInstall}
                onClick={onInstall}
                fullWidth
              >
                {installing ? "正在导入" : "下载并导入"}
              </Button>
            </Stack>
          </Paper>

          <Stack gap="md">
            <Paper withBorder radius="sm" p="lg" className="panel">
              <Group gap="sm" mb="sm">
                <Info size={18} />
                <Title order={2}>状态</Title>
              </Group>
              {result ? (
                <Alert color="teal" icon={<CheckCircle2 size={18} />} title="草稿已准备好">
                  <Stack gap={6}>
                    <Text size="sm">草稿：<Code>{result.draftName}</Code></Text>
                    <Text size="sm">路径：<Code>{result.targetDir}</Code></Text>
                    <Text size="sm">占位符：<Code>{result.placeholderId}</Code></Text>
                  </Stack>
                </Alert>
              ) : installing && currentStep ? (
                <Alert color={currentStep.level === "error" ? "red" : "blue"} icon={<LoaderCircle className="spin" size={18} />} title="正在导入">
                  <Text size="sm">{currentStep.message}</Text>
                </Alert>
              ) : (
                <Alert color="gray" icon={<TriangleAlert size={18} />} title="等待导入">
                  <Text size="sm">填写 URL 和草稿目录后开始导入。首次使用前，请确保剪映里至少存在一个本机草稿。</Text>
                </Alert>
              )}
            </Paper>

            <Paper withBorder radius="sm" p="lg" className="panel log-panel">
              <Group justify="space-between" mb="sm">
                <Title order={2}>运行日志</Title>
                <Group gap="xs">
                  <Tooltip label="打开本地日志目录">
                    <Button variant="subtle" size="xs" leftSection={<FolderOpen size={14} />} onClick={onOpenLogDir}>
                      日志
                    </Button>
                  </Tooltip>
                  <Tooltip label="复制诊断信息">
                    <Button variant="subtle" size="xs" leftSection={<ClipboardList size={14} />} onClick={onCopyDiagnostics}>
                      诊断
                    </Button>
                  </Tooltip>
                  <Badge variant="light">{logs.length}</Badge>
                </Group>
              </Group>
              <Divider mb="sm" />
              <Stack gap={8}>
                {logs.length === 0 ? (
                  <Text c="dimmed" size="sm">暂无日志。</Text>
                ) : (
                  logs.map((log) => (
                    <Text key={log.id} size="sm" className={`log-line log-${log.level}`}>
                      {log.message}
                    </Text>
                  ))
                )}
              </Stack>
            </Paper>
          </Stack>
        </div>
      </Container>
    </Box>
  );
}
