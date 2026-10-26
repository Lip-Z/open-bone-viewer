import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { BookOpen, CircleHelp, Search, X } from 'lucide-react';
import './help.css';

export type HelpTopic = 'start' | 'ct' | 'three' | 'xray' | 'privacy';

type Answer = { question: string; paragraphs: string[] };
type Topic = { id: HelpTopic; label: string; title: string; intro: string; steps: string[]; answers: Answer[] };

const topics: Topic[] = [
  {
    id: 'start', label: '第一次用', title: '先打开片子，再慢慢看懂画面',
    intro: '不需要先学会专业术语。先熟悉操作，再带着问题对照自己的检查报告。',
    steps: ['导入医院给的影像文件或文件夹，也可以直接选 ZIP 压缩包。', '在左侧选择一组影像。CT 可以逐层查看；X 光可以放大、移动。', '有不明白的画面，点旁边的答疑按钮；想继续调整，再展开下方的更多设置。'],
    answers: [
      { question: '我应该向医院要什么文件？', paragraphs: ['想逐层查看 CT 和生成三维，请获取完整的原始 DICOM 影像。医院可能提供文件夹、光盘或 ZIP；直接选择对应文件或整个文件夹即可。', '只有报告、网页链接、二维码或某一张截图，不能代替完整的 CT 数据。本软件不能直接登录医院的影像云；请先通过医院提供的方式下载文件。'] },
      { question: '为什么同一次检查出现好几组影像？', paragraphs: ['同一次 CT 可以按不同方向、清晰度或层间距重建成多组影像。软件把这些组分别列出，方便切换查看。组数不代表检查次数，也不说明病情更严重。', '“CT 影像组 1、2……”只是软件的顺序名称，不是检查日期或病情分级。看到“定位像”提示时，选择其他有连续切片的组。'] },
      { question: '它会帮我解读报告、判断病情吗？', paragraphs: ['当前版本提供看片操作和影像常识答疑，没有 AI 诊断、报告解读或个体病情分析。它不会读取你的片子后给出“哪里骨折”“是否愈合”等结论。', '可以把报告里不懂的原话、想确认的位置和自己的疑问记下来，用于和医生沟通。观察画面时，也要结合报告及实际症状。'] },
      { question: '片子打不开，是不是我的检查有问题？', paragraphs: ['打不开可能与文件格式、压缩方式、扫描方向或文件完整性有关，也可能是本机处理失败。提示本身不是病情判断。', '先确认导入的是完整影像文件，而不是报告或网页快捷方式；再试试压缩包中其他 CT 组。首版暂不支持斜切、倾斜扫描、层间距不规则及多帧 CT，MRI 也不支持。'] },
      { question: '合成示例是别人的片子吗？', paragraphs: ['不是。合成示例是程序生成的简单几何形状，只用来练习操作和确认显示是否正常，不包含真实患者。', '左侧会同时保留你导入的影像和主动打开的示例。示例不能用来对照判断自己的病情。'] },
    ],
  },
  {
    id: 'ct', label: 'CT 怎么看', title: '三个切面，是同一份 CT 的不同方向',
    intro: '可以把 CT 想成一叠薄片：从不同方向翻看同一个部位，再用十字线找到对应位置。',
    steps: ['拖动各画面下方的滑条，或把鼠标放在画面上滚动，逐层查看。', '点击画面上的一个位置，另外两个切面会跟着定位；十字线指向同一处。', '先选“看骨骼”等显示方式。想看大一点，点每个画面右上角的全屏按钮。'],
    answers: [
      { question: '四个窗口，是拍了四次吗？', paragraphs: ['不是。前三个窗口把同一组 CT 从三个方向显示：横着看（横断位）、正面看（冠状位）、侧面看（矢状位）。第四个窗口是用这组 CT 生成的三维外观。', '“正面看”和“侧面看”是便于理解的方向描述；具体左右、前后以画面上的方向标记为准。'] },
      { question: '画面上的十字线是异常标记吗？', paragraphs: ['不是。十字线只是你正在查看的位置，可以点击或拖动来移动。它不代表病灶，也不是软件识别出的骨折线。', '方向字母代表患者身体方向：R 右、L 左、A 前、P 后、S 上、I 下。画面左边不一定是身体左边，请看 R / L 标记。'] },
      { question: '越白越严重吗？“看骨骼”会改动我的片子吗？', paragraphs: ['亮暗不能直接当作病情轻重。不同组织、成像方式和显示设置都会影响灰度；这个软件也不会把白色区域自动标成异常。', '“看骨骼 / 看软组织 / 看肺部”是不同的显示预设，便于观察不同结构。调整它们只改变画面，不会改写原始影像，也不能据此判定某个部位正常或异常。'] },
      { question: '为什么滑一下，某条缝隙就不见了？', paragraphs: ['每一层显示的位置不同，结构的外观会随层面改变；三维又受显示取舍影响。单张画面无法说明整个结构。', '可以连续翻动相邻层，并在另两个方向找同一处。不要把某一层的线条、缺口或显示变化直接当成病情变化。'] },
      { question: '更多调整里的 HU、窗宽窗位是什么？', paragraphs: ['HU 是 CT 像素数值的一种单位。窗位决定主要看哪一段数值，窗宽决定这段数值怎样分成黑白灰。它们是显示控制，不是病情评分。', '不熟悉时用上方的预设就够了；随时点“看骨骼”等按钮恢复对应显示。间距和小数读数也不代表软件拥有同样精度的测量能力。'] },
    ],
  },
  {
    id: 'three', label: '三维怎么看', title: '用三维认识形状，用切片对照细节',
    intro: '三维是由 CT 计算出的外观，适合了解结构和方向。显示设置会影响它的边缘、孔洞和光滑程度。',
    steps: ['按住鼠标左键拖动来旋转，滚轮放大缩小，右键拖动来平移。', '找不到原来的角度时，点三维画面右上角的恢复视角按钮。', '先看“三维外观”；需要生成可下载的表面模型时，再展开“更多调整与导出”。'],
    answers: [
      { question: '三维上的缺口就是骨折吗？能看出长好了吗？', paragraphs: ['不能仅凭这里的三维外观得出这些结论。“三维里保留多少结构”设置、平滑、层间距及周围结构都可能改变可见表面，外观上的缺口不一定对应真实的骨折或缺损。', '三维变得光滑、连续，也不等于已经愈合。具体病情需要结合原始切片、检查报告和医生评估；当前软件不自动判断这些问题。'] },
      { question: '“主体预览”和“全部结构”有什么区别？', paragraphs: ['主体预览会尝试保留主要相连的组织，减少与它分离的扫描床等遮挡。它也可能把分离的身体部位一起隐藏；与身体相连的支撑物仍可能留下。', '觉得少了东西时，切换“全部结构”对照。这个开关只影响三维外观，不改变原始切片，也不参与表面模型和 STL 导出。'] },
      { question: '“三维里保留多少结构”调高调低，为什么形状变了？', paragraphs: ['这里的数值控制哪些 CT 数值更容易被显示出来。调高后，一些较低数值的结构可能消失；调低后，周围结构可能一起出现。查看表面模型时，调整后需要重新生成才会更新。', '这是查看同一份数据的不同方式，不是身体在发生变化。表面平滑也只是让模型外观更平顺，不能补回扫描中没有的细节。'] },
      { question: '能把单独一块骨头自动取出来吗？', paragraphs: ['当前不能。表面模型按你选的数值范围提取结构，可能同时包含多块骨头、石膏或扫描床。范围设置只能限制生成区域，不能自动识别并分离某块骨头。', 'STL 是计算生成的表面文件；NRRD 是带空间信息的原始 CT 数值文件。只想看片时，无需导出它们；生成的模型也不是经过医疗用途验证的成品。'] },
    ],
  },
  {
    id: 'xray', label: 'X 光怎么看', title: '先看完整画面，再放大想了解的位置',
    intro: 'X 光是一张投影图，不同深度的结构会重叠。这里可以移动、放大和调整显示，方便对照报告中的描述。',
    steps: ['用加减按钮或鼠标滚轮放大缩小，按住画面拖动来移动。', '画面太暗或太灰时，展开更多显示调整，试着调亮度和对比度。', '调乱了就点“恢复初始显示”；右上角可以全屏查看。'],
    answers: [
      { question: '为什么不同角度的 X 光，看起来差别很大？', paragraphs: ['X 光把不同深度的结构叠在一张图上。拍摄方向或摆位不同，重叠关系和外观都会变化；不同显示设置也会影响亮暗。', '不能只把两张图放在一起，就将外观差别认定为病情变好或变坏。比较时还需要知道拍摄部位、方向和检查报告。'] },
      { question: '放大以后能量出准确的毫米吗？', paragraphs: ['本软件目前没有提供临床测量功能。普通截图或照片通常没有可靠的毫米标定；放大只是把画面显示得更大，不能增加原来没有的细节。', '画面上的 100% 表示适应窗口的初始显示大小，不是身体的实际大小。'] },
      { question: '只有一张 X 光或 CT 截图，可以生成三维吗？', paragraphs: ['不可以。当前三维功能需要一整组空间位置完整、且在支持范围内的 CT DICOM 切片。单张 X 光、CT 截图或报告照片只能作为二维图片查看。', '亮度、对比度和缩放只改变显示；下载 PNG 得到的是显示图，不会替代医院的原始 DICOM 文件。'] },
    ],
  },
  {
    id: 'privacy', label: '我的数据', title: '影像在自己的电脑上处理',
    intro: '不用账号。安装完成后，看片和这些答疑都可以离线使用。请把影像副本、截图和导出文件都当作个人资料妥善保存。',
    steps: ['选择文件后，软件会在本机保存一份供处理和下次打开使用。', '它不会改写你最初选择的文件；从列表移除只会删除软件保存的那份数据及生成结果。', '如果想分享截图或模型，先检查有没有姓名、编号等信息，并确认分享对象。'],
    answers: [
      { question: '影像会上传吗？答疑会把我的问题发出去吗？', paragraphs: ['当前软件在本机处理影像，没有影像上传到云端、账号登录或统计服务。这些答疑是随软件提供的本地文字，搜索也在浏览器内完成，不会发送问题或片子。', '首次安装需要联网下载软件依赖。如果你主动点击答疑末尾的外部资料链接，会打开对应网站；软件不会把你的影像附带发送过去。'] },
      { question: '把姓名藏起来了，就算已经脱敏了吗？', paragraphs: ['不算。导入副本可能仍有原来的身份信息，片子本身也可能印着姓名或编号。软件使用通用名称显示列表，并不代表已经清除了文件里的个人信息。', '软件不自动脱敏。准备分享或公开截图、PNG、NRRD、STL 时，都应先检查可能暴露的个人资料。开源代码仓库不包含你的真实影像。'] },
      { question: '关掉页面后，片子还在吗？怎样移除？', paragraphs: ['在。导入影像的本机副本和生成结果会保留下来，方便下次打开。关闭浏览器页面不会删除它们；关闭运行服务的窗口才会停止本地服务。', '点击左侧影像旁的删除按钮，确认后会删除这组数据及生成结果。如果同一批文件包含多组影像，原始导入副本会在最后一组也移除后清理。你最初选择的原文件始终保留。'] },
    ],
  },
];

const HelpContext = createContext<{ openHelp: (topic?: HelpTopic) => void } | null>(null);

export function useHelp() {
  const context = useContext(HelpContext);
  if (!context) throw new Error('useHelp must be used inside HelpProvider');
  return context;
}

export function HelpProvider({ children }: { children: ReactNode }) {
  const [topicId, setTopicId] = useState<HelpTopic>('start');
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const content = useRef<HTMLDivElement>(null);
  const openHelp = useCallback((topic: HelpTopic = 'start') => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setTopicId(topic); setQuery(''); setIsOpen(true);
  }, []);
  const closeHelp = useCallback(() => setIsOpen(false), []);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (isOpen && !element.open) element.showModal();
    if (!isOpen && element.open) {
      element.close();
      if (opener.current?.isConnected) opener.current.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previous; };
  }, [isOpen]);

  useEffect(() => { if (content.current) content.current.scrollTop = 0; }, [topicId, query, isOpen]);

  const topic = topics.find(item => item.id === topicId)!;
  const search = query.trim().toLocaleLowerCase();
  const results = search ? topics.flatMap(item => item.answers.filter(answer => [answer.question, ...answer.paragraphs].join(' ').toLocaleLowerCase().includes(search)).map(answer => ({ ...answer, category: item.label }))) : [];

  return <HelpContext.Provider value={{ openHelp }}>
    {children}
    <dialog ref={dialog} className="help-dialog" aria-labelledby="help-title" aria-describedby="help-description" onCancel={event => { event.preventDefault(); closeHelp(); }} onClose={closeHelp} onClick={event => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeHelp();
    }}>
      <header className="help-header"><div><span className="help-kicker"><BookOpen size={14} /> 看片答疑</span><h2 id="help-title">看懂画面，从这里开始</h2><p id="help-description">操作说明与影像常识。这里的答疑不会读取你的片子或判断病情。</p></div><button className="help-close" autoFocus aria-label="关闭答疑" onClick={closeHelp}><X size={21} /></button></header>
      <div className="help-layout">
        <nav className="help-topics" aria-label="答疑分类">{topics.map(item => <button key={item.id} aria-pressed={topicId === item.id && !search} onClick={() => { setTopicId(item.id); setQuery(''); }}>{item.label}</button>)}<p><CircleHelp size={16} /> 从画面旁的答疑按钮进入，会直接打开相关说明。</p></nav>
        <div ref={content} className="help-content">
          <label className="help-search"><Search size={17} /><input type="search" aria-label="搜索答疑" placeholder="搜问题：四个窗口、三维缺口、隐私…" value={query} onChange={event => setQuery(event.target.value)} /></label>
          {search ? <section aria-label="答疑搜索结果"><h3 className="help-result-title" aria-live="polite">找到 {results.length} 个相关问题</h3>{results.length ? results.map(answer => <AnswerCard key={answer.question} answer={answer} category={answer.category} expanded />) : <div className="help-no-results"><p>暂时没有找到这个问题。</p><p>试试“切片”“三维”“文件”这样的词，或选择左侧分类。这里暂不提供在线提问。</p></div>}</section> : <section key={topic.id} aria-label={topic.label}><div className="help-topic-intro"><h3>{topic.title}</h3><p>{topic.intro}</p><ol>{topic.steps.map(step => <li key={step}>{step}</li>)}</ol></div><h4 className="help-faq-title">你可能想问</h4>{topic.answers.map((answer, index) => <AnswerCard key={answer.question} answer={answer} expanded={index === 0} />)}</section>}
          <footer className="help-sources"><strong>想进一步了解影像检查？</strong><p>以下是 ACR / RSNA 面向公众的检查介绍（英文）。点击会访问外部网站。</p><div><a href="https://www.radiologyinfo.org/en/info/bodyct" target="_blank" rel="noreferrer">CT 检查介绍 ↗</a><a href="https://www.radiologyinfo.org/en/info/bonerad" target="_blank" rel="noreferrer">骨骼 X 光介绍 ↗</a></div></footer>
        </div>
      </div>
    </dialog>
  </HelpContext.Provider>;
}

function AnswerCard({ answer, expanded, category }: { answer: Answer; expanded?: boolean; category?: string }) {
  return <details className="help-answer" open={expanded || undefined}><summary>{category && <span>{category}</span>}{answer.question}</summary><div>{answer.paragraphs.map(paragraph => <p key={paragraph}>{paragraph}</p>)}</div></details>;
}
