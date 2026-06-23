import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import {
  EXPORT_SETTINGS_SCHEMA_VERSION,
  LAYER_DOCUMENT_SCHEMA_VERSION,
  type Layer,
  type LayerDocument,
  type TextLayer,
} from "@flower/design-core";
import { createApiClient, type HealthResponse } from "./api/client";
import { FabricCanvas } from "./canvas/FabricCanvas";
import { listLayersForDisplay, updateLayerProperty, updateTextLayerContent } from "./canvas/layerFabricModel";
import { addImageAssetLayer, addSvgAssetLayer, addTextLayer } from "./editorActions";
import "./styles.css";

type HealthState =
  | { status: "loading" }
  | { status: "ready"; health: HealthResponse }
  | { status: "error"; message: string };

type WorkbenchView = "operator" | "operator_config" | "admin";
type OutputFormat = "png" | "svg" | "dxf";

interface RoleMeta {
  accent: string;
  description: string;
  icon: IconName;
  label: string;
  shortLabel: string;
}

interface OrderRow {
  ai: "待识别" | "已识别" | "待复核";
  id: string;
  mark: string;
  paidAt: string;
  qty: number | string;
  status: "已审核" | "已发货" | "待打单" | "已退款" | "风控中" | "已忽略";
  summary: string;
}

const apiClient = createApiClient();

const VIEW_LABELS: Record<WorkbenchView, string> = {
  operator: "操作员端",
  operator_config: "操作员配置端",
  admin: "管理员端",
};

const ROLE_META: Record<WorkbenchView, RoleMeta> = {
  operator: {
    accent: "#2fd4a8",
    description: "粘单 · 解析 · 排版 · 生成 —— 日常量产主台",
    icon: "wand",
    label: "操作员端",
    shortLabel: "日常量产",
  },
  operator_config: {
    accent: "#7aa2ff",
    description: "抓取调度 · 订单监控 · 字体素材库",
    icon: "gauge",
    label: "配置端",
    shortLabel: "产线配置",
  },
  admin: {
    accent: "#e3b34a",
    description: "AI 识别规则 · 提示词观测 · IP 敏感",
    icon: "lock",
    label: "管理员端",
    shortLabel: "识别规则",
  },
};

const VIEW_CARDS: Record<WorkbenchView, string[]> = {
  operator: ["order", "result", "layers", "output"],
  operator_config: ["fetch", "library"],
  admin: ["order", "result", "layers", "fields", "background", "prompt", "output"],
};

const ORDER_ROWS: OrderRow[] = [
  {
    ai: "待识别",
    id: "4094810918",
    mark: "AI未识别",
    paidAt: "2026-06-22 09:12",
    qty: 4,
    status: "已审核",
    summary: "4 件生日花木盒；按备注拆件",
  },
  {
    ai: "已识别",
    id: "4094810991",
    mark: "AI已处理",
    paidAt: "2026-06-22 09:58",
    qty: 1,
    status: "待打单",
    summary: "Avery · Rose · Font 4",
  },
  {
    ai: "待复核",
    id: "4094811020",
    mark: "复核",
    paidAt: "2026-06-22 10:27",
    qty: 2,
    status: "风控中",
    summary: "含其他商品；需确认是否生产",
  },
  {
    ai: "待识别",
    id: "4094811186",
    mark: "AI未识别",
    paidAt: "2026-06-22 11:03",
    qty: "—",
    status: "已退款",
    summary: "退款关键词命中，默认不生成",
  },
];

const FIELD_RULES = [
  { key: "field1", label: "info1", rule: "刻字内容：提取客户要刻的名字；只返回名字本身。" },
  { key: "field2", label: "info2", rule: "出生花：按客户备注里的花名匹配素材库 flower_name。" },
  { key: "field3", label: "info3", rule: "字体：只允许返回已配置字体枚举；不确定则 error。" },
];

export function App() {
  const [healthState, setHealthState] = useState<HealthState>({ status: "loading" });
  const [activeView, setActiveView] = useState<WorkbenchView>("operator");
  const [entryVisible, setEntryVisible] = useState(true);
  const [productRailCollapsed, setProductRailCollapsed] = useState(true);
  const [document, setDocument] = useState<LayerDocument>(() => createSampleLayerDocument());
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>("layer_name");
  const [orderRemark, setOrderRemark] = useState(defaultOrderRemark);
  const [queueIndex, setQueueIndex] = useState(1);
  const [parseResult, setParseResult] = useState("（点「解析」后显示本单识别结果）");
  const [promptPreview, setPromptPreview] = useState("解析后显示本次实际发出的提示词。");
  const [statusMessage, setStatusMessage] = useState("等待解析；识别结果不会自动生成最终文件。");
  const [fetchEnabled, setFetchEnabled] = useState(false);
  const [autoParse, setAutoParse] = useState(false);
  const [scrapeFrom, setScrapeFrom] = useState("2026-06-22T09:00");
  const [ordersQuery, setOrdersQuery] = useState("");
  const [ordersAiFilter, setOrdersAiFilter] = useState("全部AI状态");
  const [selectedFormats, setSelectedFormats] = useState<Record<OutputFormat, boolean>>({
    dxf: true,
    png: true,
    svg: true,
  });
  const [outputDirectory, setOutputDirectory] = useState("outputs");
  const [fileName, setFileName] = useState("4094810918-1");
  const assetInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;

    apiClient
      .health()
      .then((health) => {
        if (!cancelled) {
          setHealthState({ status: "ready", health });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setHealthState({
            status: "error",
            message: error instanceof Error ? error.message : "服务未连接",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const selectedLayer = useMemo(
    () => findLayerById(document.layers, selectedLayerId),
    [document.layers, selectedLayerId],
  );
  const selectedTextLayer = selectedLayer?.type === "text" ? selectedLayer : null;
  const visibleLayers = useMemo(() => listLayersForDisplay(document.layers), [document.layers]);
  const filteredOrders = useMemo(
    () => filterOrders(ORDER_ROWS, ordersQuery, ordersAiFilter),
    [ordersAiFilter, ordersQuery],
  );
  const activeMeta = ROLE_META[activeView];

  const enterView = useCallback((view: WorkbenchView) => {
    setActiveView(view);
    setEntryVisible(false);
  }, []);

  const handleParse = useCallback(() => {
    const parsed = parseRemark(orderRemark, queueIndex);
    setParseResult(parsed.result);
    setPromptPreview(parsed.prompt);
    setFileName(parsed.fileName);
    setStatusMessage("已解析，等待人工复核后点「生成」。");
    setDocument((current) => {
      const textLayer = findLayerById(current.layers, "layer_name");
      if (textLayer?.type !== "text") {
        return current;
      }
      return updateTextLayerContent(current, textLayer.id, parsed.name);
    });
  }, [orderRemark, queueIndex]);

  const handlePropertyPatch = useCallback(
    (patch: Parameters<typeof updateLayerProperty>[2]) => {
      if (!selectedLayerId) {
        return;
      }

      setDocument((currentDocument) => updateLayerProperty(currentDocument, selectedLayerId, patch));
    },
    [selectedLayerId],
  );

  const handleTextContentChange = useCallback(
    (text: string) => {
      if (!selectedLayerId) {
        return;
      }
      setDocument((currentDocument) => updateTextLayerContent(currentDocument, selectedLayerId, text));
      setStatusMessage("文字图层已更新。");
    },
    [selectedLayerId],
  );

  const handleAddTextLayer = useCallback(() => {
    const result = addTextLayer(document, { text: "新文字" });
    setDocument(result.document);
    setSelectedLayerId(result.layerId);
    setStatusMessage("已添加文字图层。");
  }, [document]);

  const handleChooseAsset = useCallback(() => {
    assetInputRef.current?.click();
  }, []);

  const handleAssetFileChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.currentTarget.files?.[0];
      event.currentTarget.value = "";
      if (!file) {
        return;
      }

      void createImportedLayer(document, file)
        .then((result) => {
          setDocument(result.document);
          setSelectedLayerId(result.layerId);
          setStatusMessage(`已添加图片图层：${file.name}`);
        })
        .catch((error: unknown) => {
          setStatusMessage(error instanceof Error ? error.message : "素材导入失败。");
        });
    },
    [document],
  );

  const handleGenerate = useCallback(() => {
    const formats = (Object.entries(selectedFormats) as Array<[OutputFormat, boolean]>)
      .filter(([, enabled]) => enabled)
      .map(([format]) => format.toUpperCase())
      .join(" / ");
    setStatusMessage(`已准备生成 ${fileName || "未命名"}：${formats || "未选择格式"}。`);
  }, [fileName, selectedFormats]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <nav className="menu-strip" aria-label="主菜单">
          {["文件", "导入", "设置", "帮助"].map((label) => (
            <button className="menu-button" key={label} type="button">
              {label}
            </button>
          ))}
        </nav>
        <div className="view-switcher">
          <span>切端</span>
          <select
            aria-label="切换工作台"
            onChange={(event) => setActiveView(event.currentTarget.value as WorkbenchView)}
            value={activeView}
          >
            {(Object.keys(VIEW_LABELS) as WorkbenchView[]).map((view) => (
              <option key={view} value={view}>
                {VIEW_LABELS[view]}
              </option>
            ))}
          </select>
        </div>
      </header>

      <section className="workbench-frame" aria-label="flower web workbench">
        <ProductRail
          collapsed={productRailCollapsed}
          onToggle={() => setProductRailCollapsed((value) => !value)}
        />

        <section className="center-column" aria-label={activeView === "operator_config" ? "实时订单" : "实时画板"}>
          <div className="center-head">
            <div>
              <h1>{activeView === "operator_config" ? "实时订单 · 扩展抓取已入库" : "实时画板"}</h1>
              <p>
                {activeView === "operator_config"
                  ? "配置端不编辑画布，只监控抓取调度与订单状态。"
                  : "白底代表木料预览；拖动画布元素会同步到图层数据。"}
              </p>
            </div>
            <div className="zoom-chip">{activeView === "operator_config" ? `${filteredOrders.length} 单` : "100%"}</div>
          </div>
          {activeView === "operator_config" ? (
            <OrdersBoard
              aiFilter={ordersAiFilter}
              orders={filteredOrders}
              query={ordersQuery}
              onChangeAiFilter={setOrdersAiFilter}
              onChangeQuery={setOrdersQuery}
            />
          ) : (
            <div className="canvas-stage">
              <FabricCanvas
                document={document}
                selectedLayerId={selectedLayerId}
                onChangeDocument={setDocument}
                onSelectLayer={setSelectedLayerId}
              />
            </div>
          )}
        </section>

        <aside className="function-panel" aria-label="功能区">
          <div className="function-title">功能区</div>
          {VIEW_CARDS[activeView].map((card) => (
            <FunctionCard
              key={card}
              card={card}
              document={document}
              fileName={fileName}
              fetchEnabled={fetchEnabled}
              outputDirectory={outputDirectory}
              parseResult={parseResult}
              promptPreview={promptPreview}
              queueIndex={queueIndex}
              remark={orderRemark}
              scrapeFrom={scrapeFrom}
              selectedFormats={selectedFormats}
              selectedLayer={selectedLayer}
              selectedLayerId={selectedLayerId}
              selectedTextLayer={selectedTextLayer}
              statusMessage={statusMessage}
              visibleLayers={visibleLayers}
              autoParse={autoParse}
              onAddText={handleAddTextLayer}
              onAssetFileChange={handleAssetFileChange}
              onChangeAutoParse={setAutoParse}
              onChangeDocument={setDocument}
              onChangeFetch={setFetchEnabled}
              onChangeFileName={setFileName}
              onChangeFormat={(format, enabled) =>
                setSelectedFormats((current) => ({ ...current, [format]: enabled }))
              }
              onChangeOutputDirectory={setOutputDirectory}
              onChangeProperty={handlePropertyPatch}
              onChangeQueue={setQueueIndex}
              onChangeRemark={setOrderRemark}
              onChangeScrapeFrom={setScrapeFrom}
              onChangeText={handleTextContentChange}
              onChooseAsset={handleChooseAsset}
              onGenerate={handleGenerate}
              onParse={handleParse}
              onSelectLayer={setSelectedLayerId}
            />
          ))}
          <input
            accept=".svg,.png,.jpg,.jpeg,.webp,.bmp"
            className="visually-hidden-file"
            onChange={handleAssetFileChange}
            ref={assetInputRef}
            type="file"
          />
        </aside>
      </section>

      {entryVisible ? (
        <EntryOverlay healthState={healthState} onEnter={enterView} onClose={() => setEntryVisible(false)} />
      ) : null}
    </main>
  );
}

function ProductRail({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <aside className={collapsed ? "product-rail is-collapsed" : "product-rail"} aria-label="产品">
      <button className="rail-toggle" onClick={onToggle} title={collapsed ? "展开产品列" : "收起产品列"} type="button">
        {collapsed ? "«" : "»"}
      </button>
      {!collapsed ? <div className="rail-title">产品</div> : null}
      <button className="product-pill active" type="button">
        {collapsed ? "生" : "生日花卡"}
      </button>
      <button className="product-pill" type="button">
        {collapsed ? "+" : "+ 新建产品"}
      </button>
    </aside>
  );
}

function FunctionCard({
  autoParse,
  card,
  document,
  fetchEnabled,
  fileName,
  onAddText,
  onAssetFileChange,
  onChangeAutoParse,
  onChangeDocument,
  onChangeFetch,
  onChangeFileName,
  onChangeFormat,
  onChangeOutputDirectory,
  onChangeProperty,
  onChangeQueue,
  onChangeRemark,
  onChangeScrapeFrom,
  onChangeText,
  onChooseAsset,
  onGenerate,
  onParse,
  onSelectLayer,
  outputDirectory,
  parseResult,
  promptPreview,
  queueIndex,
  remark,
  scrapeFrom,
  selectedFormats,
  selectedLayer,
  selectedLayerId,
  selectedTextLayer,
  statusMessage,
  visibleLayers,
}: {
  autoParse: boolean;
  card: string;
  document: LayerDocument;
  fetchEnabled: boolean;
  fileName: string;
  onAddText: () => void;
  onAssetFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onChangeAutoParse: (value: boolean) => void;
  onChangeDocument: (document: LayerDocument) => void;
  onChangeFetch: (value: boolean) => void;
  onChangeFileName: (value: string) => void;
  onChangeFormat: (format: OutputFormat, enabled: boolean) => void;
  onChangeOutputDirectory: (value: string) => void;
  onChangeProperty: (patch: Parameters<typeof updateLayerProperty>[2]) => void;
  onChangeQueue: (value: number) => void;
  onChangeRemark: (value: string) => void;
  onChangeScrapeFrom: (value: string) => void;
  onChangeText: (value: string) => void;
  onChooseAsset: () => void;
  onGenerate: () => void;
  onParse: () => void;
  onSelectLayer: (layerId: string | null) => void;
  outputDirectory: string;
  parseResult: string;
  promptPreview: string;
  queueIndex: number;
  remark: string;
  scrapeFrom: string;
  selectedFormats: Record<OutputFormat, boolean>;
  selectedLayer: Layer | null;
  selectedLayerId: string | null;
  selectedTextLayer: TextLayer | null;
  statusMessage: string;
  visibleLayers: Layer[];
}) {
  if (card === "order") {
    return (
      <Card title="订单信息">
        <textarea
          className="field-textarea"
          onChange={(event) => onChangeRemark(event.currentTarget.value)}
          value={remark}
        />
        <div className="button-row">
          <button className="secondary-action" type="button">
            导入
          </button>
          <button className="primary-action" onClick={onParse} type="button">
            <Icon name="wand" />
            解析
          </button>
          <button className="secondary-action" onClick={() => onChangeRemark("")} type="button">
            清空
          </button>
        </div>
        <div className="queue-row">
          <span>第 {queueIndex}/4 单</span>
          <button onClick={() => onChangeQueue(Math.max(1, queueIndex - 1))} type="button">
            ‹ 上一笔
          </button>
          <button onClick={() => onChangeQueue(Math.min(4, queueIndex + 1))} type="button">
            下一笔 ›
          </button>
        </div>
      </Card>
    );
  }

  if (card === "result") {
    return (
      <Card title="解析结果">
        <pre className="readonly-box">{parseResult}</pre>
      </Card>
    );
  }

  if (card === "fetch") {
    return (
      <Card title="抓取订单">
        <p className="status-copy">服务：进入本端自动查询（或点「刷新」）</p>
        <div className="switch-row">
          <Toggle checked={fetchEnabled} label="自动抓取" onChange={onChangeFetch} />
          <Toggle checked={autoParse} label="自动识别" onChange={onChangeAutoParse} />
        </div>
        <label className="stack-field">
          <span>定时抓取 · 重抓起点</span>
          <input
            onChange={(event) => onChangeScrapeFrom(event.currentTarget.value)}
            type="datetime-local"
            value={scrapeFrom}
          />
        </label>
        <p className="muted-note">
          自动抓取控制店小秘抓单；自动识别只控制新订单进前端后是否自动解析，仍需人工点「生成」。
        </p>
      </Card>
    );
  }

  if (card === "library") {
    return (
      <Card title="字体库 / 素材库">
        <LibraryRow count={2} label="字体库 · Birthmonth + Script" />
        <LibraryRow count={27} label="素材库 · BirthMonth flowers" />
        <p className="muted-note">网页原型保留「点击上传」位置；真实导入仍以桌面端/服务端路径为准。</p>
      </Card>
    );
  }

  if (card === "layers") {
    return (
      <Card title="图层">
        <div className="canvas-size">画布尺寸 {document.canvas.width} × {document.canvas.height}</div>
        <div className="layer-list">
          {visibleLayers.map((layer) => (
            <button
              className={layer.id === selectedLayerId ? "layer-row active" : "layer-row"}
              key={layer.id}
              onClick={() => onSelectLayer(layer.id)}
              type="button"
            >
              <span className="drag-handle">⠿</span>
              <span className="layer-icon">{layer.type === "text" ? "T" : "▣"}</span>
              <span className="layer-name">{layer.name}</span>
              <span className="layer-dim">{layer.type === "text" ? `${layer.style.fontSize}px` : `${Math.round(layer.width)}`}</span>
            </button>
          ))}
        </div>
        <div className="button-row">
          <button className="primary-action" onClick={onAddText} type="button">
            + 文字图层
          </button>
          <button className="secondary-action" onClick={onChooseAsset} type="button">
            + 图片图层
          </button>
          <input
            accept=".svg,.png,.jpg,.jpeg,.webp,.bmp"
            className="visually-hidden-file"
            onChange={onAssetFileChange}
            type="file"
          />
        </div>
        {selectedLayer ? (
          <GeometryEditor layer={selectedLayer} onChange={onChangeProperty} />
        ) : (
          <p className="muted-note">未选择图层。</p>
        )}
        <TextEditor layer={selectedTextLayer} onChangeText={onChangeText} />
      </Card>
    );
  }

  if (card === "fields") {
    return (
      <Card badge="仅管理员 · IP" title="字段">
        <div className="field-rule-list">
          {FIELD_RULES.map((field) => (
            <div className="field-rule-card" key={field.key}>
              <span>{field.label}</span>
              <textarea defaultValue={field.rule} />
            </div>
          ))}
        </div>
        <button className="secondary-action fit-button" type="button">
          添加字段 +
        </button>
      </Card>
    );
  }

  if (card === "background") {
    return (
      <Card badge="仅管理员 · IP" title="背景提示词">
        <textarea
          className="compact-textarea"
          defaultValue="你正在解析生日花木盒定制订单。所有字段、枚举与规则以后台当前配置为准。"
        />
      </Card>
    );
  }

  if (card === "prompt") {
    return (
      <Card badge="解析可观测②" title="本次提示词（实际发出）">
        <button className="primary-action fit-button" type="button">
          预览
        </button>
        <pre className="readonly-box prompt-box">{promptPreview}</pre>
      </Card>
    );
  }

  if (card === "output") {
    return (
      <Card title="输出设置">
        <label className="inline-field">
          <span>输出目录</span>
          <input onChange={(event) => onChangeOutputDirectory(event.currentTarget.value)} value={outputDirectory} />
        </label>
        <div className="format-row">
          {(Object.keys(selectedFormats) as OutputFormat[]).map((format) => (
            <label key={format}>
              <input
                checked={selectedFormats[format]}
                onChange={(event) => onChangeFormat(format, event.currentTarget.checked)}
                type="checkbox"
              />
              {format.toUpperCase()}
            </label>
          ))}
        </div>
        <label className="inline-field">
          <span>文件名</span>
          <input onChange={(event) => onChangeFileName(event.currentTarget.value)} value={fileName} />
        </label>
        <div className="generate-row">
          <p>{statusMessage}</p>
          <button className="primary-action" onClick={onGenerate} type="button">
            生成
          </button>
        </div>
      </Card>
    );
  }

  return null;
}

function Card({
  badge,
  children,
  title,
}: {
  badge?: string;
  children: React.ReactNode;
  title: string;
}) {
  return (
    <section className="function-card">
      <div className="card-head">
        <h2>{title}</h2>
        {badge ? <span>{badge}</span> : null}
      </div>
      {children}
    </section>
  );
}

function OrdersBoard({
  aiFilter,
  onChangeAiFilter,
  onChangeQuery,
  orders,
  query,
}: {
  aiFilter: string;
  onChangeAiFilter: (value: string) => void;
  onChangeQuery: (value: string) => void;
  orders: OrderRow[];
  query: string;
}) {
  return (
    <section className="orders-board">
      <div className="orders-toolbar">
        <button className="danger-action" type="button">
          ✕ 删除选中
        </button>
        <button className="secondary-action fit-button" type="button">
          刷新
        </button>
      </div>
      <div className="orders-filter">
        <span>付款</span>
        <input placeholder="从 Y-M-D" />
        <input placeholder="到 Y-M-D" />
        <select defaultValue="全部状态">
          {["全部状态", "已审核", "已发货", "待打单", "已退款", "风控中", "已忽略"].map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <select onChange={(event) => onChangeAiFilter(event.currentTarget.value)} value={aiFilter}>
          {["全部AI状态", "待识别", "已识别", "待复核"].map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <input
          onChange={(event) => onChangeQuery(event.currentTarget.value)}
          placeholder="搜索订单号 / 备注"
          value={query}
        />
      </div>
      <p className="review-hint">复核 = 订单 AI 标记与库内状态冲突，需人工裁决；勾「待复核」筛出。</p>
      <div className="orders-table-wrap">
        <table className="orders-table">
          <thead>
            <tr>
              <th>订单号</th>
              <th>付款时间</th>
              <th>状态（店小秘）</th>
              <th>标签</th>
              <th>件数</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr className={`order-${order.ai}`} key={order.id}>
                <td>{order.id}</td>
                <td>{order.paidAt}</td>
                <td>{order.status}</td>
                <td>{order.mark}</td>
                <td>{order.qty}</td>
                <td>{order.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function GeometryEditor({
  layer,
  onChange,
}: {
  layer: Layer;
  onChange: (patch: Parameters<typeof updateLayerProperty>[2]) => void;
}) {
  const scale = Number(((layer.scaleX + layer.scaleY) / 2).toFixed(3));

  return (
    <div className="geometry-grid">
      <NumberField label="位置X" value={layer.x} onChange={(x) => onChange({ x })} />
      <NumberField label="Y" value={layer.y} onChange={(y) => onChange({ y })} />
      <NumberField label="缩放" step={0.05} value={scale} onChange={(nextScale) => onChange({ scale: nextScale })} />
      <NumberField label="旋转" value={layer.rotation} onChange={(rotation) => onChange({ rotation })} />
      <Toggle checked={layer.visible} label="显/隐" onChange={(visible) => onChange({ visible })} />
      <Toggle checked={layer.locked} label="锁/解" onChange={(locked) => onChange({ locked })} />
    </div>
  );
}

function TextEditor({
  layer,
  onChangeText,
}: {
  layer: TextLayer | null;
  onChangeText: (text: string) => void;
}) {
  if (!layer) {
    return null;
  }

  return (
    <label className="stack-field text-layer-editor">
      <span>文本</span>
      <textarea onChange={(event) => onChangeText(event.currentTarget.value)} value={layer.text} />
    </label>
  );
}

function NumberField({
  label,
  onChange,
  step = 1,
  value,
}: {
  label: string;
  onChange: (value: number) => void;
  step?: number;
  value: number;
}) {
  return (
    <label className="mini-number">
      <span>{label}</span>
      <input
        onChange={(event) => {
          const next = Number(event.currentTarget.value);
          if (Number.isFinite(next)) {
            onChange(next);
          }
        }}
        step={step}
        type="number"
        value={Number(value.toFixed(3))}
      />
    </label>
  );
}

function Toggle({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="toggle">
      <input checked={checked} onChange={(event) => onChange(event.currentTarget.checked)} type="checkbox" />
      <span>{label}</span>
    </label>
  );
}

function LibraryRow({
  count,
  label,
}: {
  count: number;
  label: string;
}) {
  return (
    <div className="library-row">
      <span>{label}（{count} 个）</span>
      <button className="secondary-action fit-button" type="button">
        点击上传
      </button>
    </div>
  );
}

function EntryOverlay({
  healthState,
  onClose,
  onEnter,
}: {
  healthState: HealthState;
  onClose: () => void;
  onEnter: (view: WorkbenchView) => void;
}) {
  const serviceText = healthState.status === "ready" ? "服务 已连" : "服务 —";

  return (
    <section className="entry-overlay" aria-label="选择工作台">
      <div className="entry-panel">
        <div className="entry-top">
          <div className="brand-block">
            <span className="brand-mark">
              <Icon name="flower" />
            </span>
            <strong>flower</strong>
            <span>雕刻素材工作台</span>
          </div>
          <div className="entry-chips">
            <span>{serviceText}</span>
            <span>抓取 —</span>
            <span>积压 4</span>
          </div>
        </div>
        <p className="entry-label">选择工作台</p>
        <button className="entry-hero" onClick={() => onEnter("operator")} type="button">
          <span className="entry-icon" style={{ color: ROLE_META.operator.accent }}>
            <Icon name={ROLE_META.operator.icon} />
          </span>
          <span>
            <strong>{ROLE_META.operator.label}</strong>
            <small>{ROLE_META.operator.description}</small>
          </span>
          <span className="entry-count">
            <strong>4</strong>
            <small>待处理</small>
          </span>
          <span className="entry-go">进入</span>
        </button>
        <div className="entry-grid">
          {(["operator_config", "admin"] as WorkbenchView[]).map((view) => (
            <button className="entry-card" key={view} onClick={() => onEnter(view)} type="button">
              <span className="entry-icon" style={{ color: ROLE_META[view].accent }}>
                <Icon name={ROLE_META[view].icon} />
              </span>
              <span>
                <strong>{ROLE_META[view].label}</strong>
                <small>{ROLE_META[view].description}</small>
              </span>
            </button>
          ))}
        </div>
        <div className="entry-footer">
          <span>进入后顶部「切端」可随时切换</span>
          <button onClick={onClose} type="button">
            直接查看界面
          </button>
        </div>
      </div>
    </section>
  );
}

type IconName = "flower" | "gauge" | "lock" | "wand";

function Icon({ name }: { name: IconName }) {
  if (name === "flower") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M12 13c-3.6-1.3-5.4-3.6-4.8-6.1 2.7-.3 4.6 1.1 4.8 4.4.2-3.3 2.1-4.7 4.8-4.4.6 2.5-1.2 4.8-4.8 6.1Z" />
        <path d="M12 13c-3.2.4-5.1 2.2-5.1 4.7 2.5.9 4.8-.1 5.1-3 .3 2.9 2.6 3.9 5.1 3 0-2.5-1.9-4.3-5.1-4.7Z" />
        <path d="M12 14v7" />
      </svg>
    );
  }

  if (name === "gauge") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M4 14a8 8 0 0 1 16 0" />
        <path d="M12 14l4-5" />
        <path d="M7 19h10" />
      </svg>
    );
  }

  if (name === "lock") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <rect height="10" rx="2" width="14" x="5" y="10" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M5 19l14-14" />
      <path d="M14 5l5 5" />
      <path d="M4 13l7 7" />
    </svg>
  );
}

function filterOrders(orders: OrderRow[], query: string, aiFilter: string) {
  const normalized = query.trim().toLocaleLowerCase();
  return orders.filter((order) => {
    if (aiFilter !== "全部AI状态" && order.ai !== aiFilter) {
      return false;
    }
    if (!normalized) {
      return true;
    }
    return `${order.id} ${order.summary}`.toLocaleLowerCase().includes(normalized);
  });
}

function parseRemark(remark: string, queueIndex: number) {
  const order = remark.match(/\b\d{8,}\b/)?.[0] ?? "4094810918";
  const name = remark.match(/name[:：][ \t]*([A-Za-z][A-Za-z '-]{1,24})/i)?.[1]?.trim() ?? "Avery";
  const flower = remark.match(/flower[:：]\s*([A-Za-z -]+)/i)?.[1]?.trim() ?? "Rose";
  const font = remark.match(/font[:：]\s*([A-Za-z0-9 -]+)/i)?.[1]?.trim() ?? "Font 4";
  const fileName = `${order}-${queueIndex}`;
  const result = `订单号：${order}\n刻字内容：${name}\n出生花：${flower}\n字体：${font}\n文件名：${fileName}\n队列：第 ${queueIndex}/4 单`;
  const prompt = `provider: local preview\nmodel: front-end-prototype\n\n【字段规则】\n${FIELD_RULES.map((item) => `- ${item.label}: ${item.rule}`).join("\n")}\n\n【本次订单】\n${remark}`;

  return { fileName, name, prompt, result };
}

function findLayerById(layers: readonly Layer[], layerId: string | null): Layer | null {
  if (!layerId) {
    return null;
  }

  for (const layer of layers) {
    if (layer.id === layerId) {
      return layer;
    }

    if (layer.type === "group") {
      const child = findLayerById(layer.children, layerId);
      if (child) {
        return child;
      }
    }
  }

  return null;
}

function createSampleLayerDocument(): LayerDocument {
  return {
    schemaVersion: LAYER_DOCUMENT_SCHEMA_VERSION,
    documentId: "doc_web_style_prototype",
    projectId: "flower",
    jobId: "job_preview",
    metadata: {
      appVersion: "0.1.0",
      createdAt: "2026-06-23T00:00:00.000Z",
      orderId: "4094810918",
      templateId: "birth-flower-card",
      templateVersion: "1.0.0",
      updatedAt: "2026-06-23T00:00:00.000Z",
    },
    canvas: {
      background: { color: "#ffffff", type: "solid" },
      height: 1280,
      unit: "px",
      width: 1732,
    },
    exportSettings: {
      defaultFormats: ["svg", "png", "dxf"],
      dxf: { textMode: "paths", units: "px" },
      png: { background: "canvas", scale: 1 },
      schemaVersion: EXPORT_SETTINGS_SCHEMA_VERSION,
      svg: { includeMetadata: true, preserveText: true, preserveVector: true },
    },
    layers: [
      {
        exportable: true,
        height: 640,
        id: "layer_flower",
        inlineSvg: flowerSvg,
        locked: false,
        name: "Rose 素材",
        opacity: 1,
        preserveVector: true,
        rotation: -2,
        scaleX: 1,
        scaleY: 1,
        tags: ["sample-svg"],
        type: "svg",
        viewBox: { height: 160, width: 120, x: 0, y: 0 },
        visible: true,
        width: 520,
        x: 320,
        y: 90,
        zIndex: 1,
      },
      {
        exportable: true,
        fontRef: {
          fallbackFamilies: ["serif"],
          family: "Georgia",
          source: "system",
        },
        height: 220,
        id: "layer_name",
        layout: { mode: "box", overflow: "shrink-to-fit" },
        locked: false,
        name: "Avery 刻字",
        opacity: 1,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        style: {
          align: "center",
          fill: "#111111",
          fontSize: 190,
          letterSpacing: 0,
          lineHeight: 1.08,
        },
        tags: ["sample-text"],
        text: "Avery",
        type: "text",
        visible: true,
        width: 760,
        x: 700,
        y: 820,
        zIndex: 2,
      },
    ],
  };
}

const defaultOrderRemark = `Order 4094810918
Name: Avery
Flower: Rose
Font: Font 4
Quantity: 4 boxes`;

const flowerSvg = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 160">
  <path d="M62 72 C48 38 54 16 72 8 C88 30 82 52 62 72Z" fill="#d74862"/>
  <path d="M58 72 C30 50 22 28 34 12 C58 26 68 48 58 72Z" fill="#ef7d8f"/>
  <path d="M60 74 C86 54 106 54 114 70 C94 90 74 90 60 74Z" fill="#c93755"/>
  <path d="M60 76 C34 82 20 100 28 120 C54 118 66 98 60 76Z" fill="#f09dad"/>
  <path d="M60 76 C78 98 76 126 58 150" fill="none" stroke="#2f7d5f" stroke-width="8" stroke-linecap="round"/>
  <path d="M64 104 C84 94 102 102 108 118 C88 126 72 120 64 104Z" fill="#55a06f"/>
</svg>
`;

async function createImportedLayer(document: LayerDocument, file: File) {
  if (isSvgFile(file)) {
    return addSvgAssetLayer(document, {
      name: file.name,
      svgText: await file.text(),
    });
  }

  if (!isRasterImageFile(file)) {
    throw new Error("不支持的素材文件类型。");
  }

  const dataUrl = await readFileAsDataUrl(file);
  const size = await readImageSize(dataUrl);
  return addImageAssetLayer(document, {
    dataUrl,
    height: size.height,
    name: file.name,
    width: size.width,
  });
}

function isSvgFile(file: File): boolean {
  return file.type === "image/svg+xml" || file.name.toLocaleLowerCase().endsWith(".svg");
}

function isRasterImageFile(file: File): boolean {
  return (
    file.type.startsWith("image/") &&
    [".png", ".jpg", ".jpeg", ".webp", ".bmp"].some((extension) =>
      file.name.toLocaleLowerCase().endsWith(extension),
    )
  );
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
        return;
      }
      reject(new Error("素材文件读取失败。"));
    };
    reader.onerror = () => reject(new Error("素材文件读取失败。"));
    reader.readAsDataURL(file);
  });
}

function readImageSize(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      resolve({
        height: image.naturalHeight || 1,
        width: image.naturalWidth || 1,
      });
    };
    image.onerror = () => reject(new Error("图片素材解码失败。"));
    image.src = dataUrl;
  });
}
