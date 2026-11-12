// The Quick Access panel's words in each language Pocket XR speaks. The Gaming Mode service says which (Steam's own
// UI language, or POCKET_XR_LANG); keep the {placeholders} the same in every language.
export type Words = {
  looking: string;
  notRunning: string;
  plugIn: string;
  noTracking: string; // {glasses}
  trackingOn: string; // {glasses}
  spaceTitle: string;
  spaceLine: string;
  steadyTitle: string;
  steadyLine: string;
  offTitle: string;
  offLine: string;
  view: string;
  screen: string;
  size: string;
  recentre: string;
  buttons: string;
  sendLogs: string;
  logsLine: string;
  logsReady: string;
  logsSaved: string; // {name}
  logsFailed: string; // {error}
};

export const WORDS: Record<string, Words> = {
  en: {
    looking: "Looking for Pocket XR...",
    notRunning: "Pocket XR isn't running. Install or update it from Desktop Mode.",
    plugIn: "Plug your glasses into the Deck's USB-C port.",
    noTracking: "{glasses}: no head tracking on these glasses, so the picture is shown as it is.",
    trackingOn: "{glasses} · head tracking on",
    spaceTitle: "Screen in space",
    spaceLine: "Stays put as you turn your head.",
    steadyTitle: "Steady",
    steadyLine: "The glasses hold the screen as you move around.",
    offTitle: "Off",
    offLine: "The picture as it is, moving with your head.",
    view: "View",
    screen: "Screen",
    size: "Size",
    recentre: "Recentre",
    buttons: "Without this menu: hold L4 to recentre, hold R4 to switch view.",
    sendLogs: "Send logs to Mike",
    logsLine:
      "Saves one zip of Pocket XR's logs in Downloads, with emails, account, Wi-Fi and Bluetooth names and IP addresses taken out.",
    logsReady: "Getting the logs ready...",
    logsSaved:
      "Saved {name} in Downloads. Send it to connect@mikehaye.com from Desktop Mode, or attach it to an issue on GitHub.",
    logsFailed: "Could not make the logs: {error}",
  },
  ko: {
    looking: "Pocket XR을 찾는 중...",
    notRunning: "Pocket XR이 실행되고 있지 않아요. 데스크톱 모드에서 설치하거나 업데이트하세요.",
    plugIn: "안경을 Deck의 USB-C 포트에 연결하세요.",
    noTracking: "{glasses}: 이 안경은 헤드 트래킹이 없어서 화면을 그대로 보여 줘요.",
    trackingOn: "{glasses} · 헤드 트래킹 켜짐",
    spaceTitle: "공간에 고정된 화면",
    spaceLine: "고개를 돌려도 제자리에 있어요.",
    steadyTitle: "Steady",
    steadyLine: "움직여도 안경이 화면을 제자리에 잡아 줘요.",
    offTitle: "끄기",
    offLine: "화면을 그대로, 고개를 따라 움직여요.",
    view: "보기",
    screen: "화면",
    size: "크기",
    recentre: "가운데로",
    buttons: "메뉴 없이: L4를 길게 누르면 가운데로, R4를 길게 누르면 보기를 바꿔요.",
    sendLogs: "Mike에게 로그 보내기",
    logsLine:
      "Pocket XR 로그를 zip 하나로 다운로드 폴더에 저장해요. 이메일 주소, 계정, Wi-Fi와 Bluetooth 이름, IP 주소는 빼고 저장해요.",
    logsReady: "로그를 준비하는 중...",
    logsSaved:
      "{name} 파일을 다운로드 폴더에 저장했어요. 데스크톱 모드에서 connect@mikehaye.com으로 보내거나 GitHub 이슈에 첨부해 주세요.",
    logsFailed: "로그를 만들지 못했어요: {error}",
  },
  ja: {
    looking: "Pocket XR を探しています...",
    notRunning: "Pocket XR が動いていません。デスクトップモードでインストールまたは更新してください。",
    plugIn: "グラスを Deck の USB-C ポートにつないでください。",
    noTracking: "{glasses}：このグラスはヘッドトラッキングがないので、映像をそのまま表示します。",
    trackingOn: "{glasses} · ヘッドトラッキング オン",
    spaceTitle: "空間に固定した画面",
    spaceLine: "頭を動かしてもその場にとどまります。",
    steadyTitle: "Steady",
    steadyLine: "動き回ってもグラスが画面をその場に保ちます。",
    offTitle: "オフ",
    offLine: "映像をそのまま、頭と一緒に動きます。",
    view: "ビュー",
    screen: "画面",
    size: "サイズ",
    recentre: "正面に戻す",
    buttons: "メニューなしで：L4 長押しで正面に戻す、R4 長押しでビュー切り替え。",
    sendLogs: "Mike にログを送る",
    logsLine:
      "Pocket XR のログを 1 つの zip にしてダウンロードに保存します。メールアドレス、アカウント、Wi-Fi と Bluetooth の名前、IP アドレスは取り除かれます。",
    logsReady: "ログを準備しています...",
    logsSaved:
      "{name} をダウンロードに保存しました。デスクトップモードから connect@mikehaye.com に送るか、GitHub の Issue に添付してください。",
    logsFailed: "ログを作れませんでした：{error}",
  },
  zh_CN: {
    looking: "正在查找 Pocket XR...",
    notRunning: "Pocket XR 没有运行。请在桌面模式下安装或更新。",
    plugIn: "请把眼镜接到 Deck 的 USB-C 接口。",
    noTracking: "{glasses}：这副眼镜没有头部追踪，所以画面按原样显示。",
    trackingOn: "{glasses} · 头部追踪已开启",
    spaceTitle: "固定在空间中的屏幕",
    spaceLine: "转头时屏幕留在原处。",
    steadyTitle: "Steady",
    steadyLine: "你走动时，眼镜会把屏幕固定在原处。",
    offTitle: "关闭",
    offLine: "画面保持原样，随头部移动。",
    view: "视图",
    screen: "屏幕",
    size: "大小",
    recentre: "回到正前方",
    buttons: "不用菜单：按住 L4 回到正前方，按住 R4 切换视图。",
    sendLogs: "把日志发给 Mike",
    logsLine: "把 Pocket XR 的日志打包成一个 zip 保存到“下载”文件夹，并去掉邮箱地址、账户、Wi-Fi 和蓝牙名称以及 IP 地址。",
    logsReady: "正在准备日志...",
    logsSaved: "已将 {name} 保存到“下载”文件夹。请在桌面模式下把它发到 connect@mikehaye.com，或附加到 GitHub 上的 issue。",
    logsFailed: "无法生成日志：{error}",
  },
  zh_TW: {
    looking: "正在尋找 Pocket XR...",
    notRunning: "Pocket XR 沒有在執行。請在桌面模式中安裝或更新。",
    plugIn: "請把眼鏡接上 Deck 的 USB-C 連接埠。",
    noTracking: "{glasses}：這副眼鏡沒有頭部追蹤，所以畫面會照原樣顯示。",
    trackingOn: "{glasses} · 頭部追蹤已開啟",
    spaceTitle: "固定在空間中的螢幕",
    spaceLine: "轉頭時螢幕留在原處。",
    steadyTitle: "Steady",
    steadyLine: "你走動時，眼鏡會把螢幕固定在原處。",
    offTitle: "關閉",
    offLine: "畫面照原樣，跟著頭部移動。",
    view: "檢視",
    screen: "螢幕",
    size: "大小",
    recentre: "回到正前方",
    buttons: "不用選單：按住 L4 回到正前方，按住 R4 切換檢視。",
    sendLogs: "把記錄檔傳給 Mike",
    logsLine: "把 Pocket XR 的記錄檔打包成一個 zip 存到「下載」資料夾，並移除電子郵件地址、帳號、Wi-Fi 和藍牙名稱以及 IP 位址。",
    logsReady: "正在準備記錄檔...",
    logsSaved: "已將 {name} 儲存到「下載」資料夾。請在桌面模式中寄到 connect@mikehaye.com，或附加到 GitHub 上的 issue。",
    logsFailed: "無法產生記錄檔：{error}",
  },
  es: {
    looking: "Buscando Pocket XR...",
    notRunning: "Pocket XR no está abierto. Instálalo o actualízalo desde el modo Escritorio.",
    plugIn: "Conecta tus gafas al puerto USB-C del Deck.",
    noTracking: "{glasses}: estas gafas no tienen seguimiento de cabeza, así que la imagen se ve tal cual.",
    trackingOn: "{glasses} · seguimiento de cabeza activado",
    spaceTitle: "Pantalla en el espacio",
    spaceLine: "Se queda quieta cuando giras la cabeza.",
    steadyTitle: "Steady",
    steadyLine: "Las gafas mantienen la pantalla en su sitio mientras te mueves.",
    offTitle: "Desactivado",
    offLine: "La imagen tal cual, moviéndose con tu cabeza.",
    view: "Vista",
    screen: "Pantalla",
    size: "Tamaño",
    recentre: "Centrar",
    buttons: "Sin este menú: mantén L4 para centrar y R4 para cambiar de vista.",
    sendLogs: "Enviar registros a Mike",
    logsLine:
      "Guarda en Descargas un zip con los registros de Pocket XR, sin correos, cuentas, nombres de Wi-Fi y Bluetooth ni direcciones IP.",
    logsReady: "Preparando los registros...",
    logsSaved:
      "{name} se guardó en Descargas. Envíalo a connect@mikehaye.com desde el modo Escritorio o adjúntalo a un issue en GitHub.",
    logsFailed: "No se pudieron crear los registros: {error}",
  },
  pt_BR: {
    looking: "Procurando o Pocket XR...",
    notRunning: "O Pocket XR não está aberto. Instale ou atualize pelo modo Desktop.",
    plugIn: "Conecte seus óculos na porta USB-C do Deck.",
    noTracking: "{glasses}: estes óculos não têm rastreamento de cabeça, então a imagem aparece como está.",
    trackingOn: "{glasses} · rastreamento de cabeça ligado",
    spaceTitle: "Tela no espaço",
    spaceLine: "Fica parada quando você vira a cabeça.",
    steadyTitle: "Steady",
    steadyLine: "Os óculos seguram a tela no lugar enquanto você se move.",
    offTitle: "Desligado",
    offLine: "A imagem como está, movendo com a sua cabeça.",
    view: "Visão",
    screen: "Tela",
    size: "Tamanho",
    recentre: "Centralizar",
    buttons: "Sem este menu: segure L4 para centralizar e R4 para trocar a visão.",
    sendLogs: "Enviar logs para o Mike",
    logsLine:
      "Salva em Downloads um zip com os logs do Pocket XR, sem e-mails, conta, nomes de Wi-Fi e Bluetooth nem endereços IP.",
    logsReady: "Preparando os logs...",
    logsSaved:
      "{name} foi salvo em Downloads. Envie para connect@mikehaye.com pelo modo Desktop ou anexe a uma issue no GitHub.",
    logsFailed: "Não foi possível criar os logs: {error}",
  },
  fr: {
    looking: "Recherche de Pocket XR…",
    notRunning: "Pocket XR n'est pas lancé. Installez-le ou mettez-le à jour depuis le mode Bureau.",
    plugIn: "Branchez vos lunettes sur le port USB-C du Deck.",
    noTracking: "{glasses} : ces lunettes n'ont pas de suivi de la tête, l'image s'affiche donc telle quelle.",
    trackingOn: "{glasses} · suivi de la tête activé",
    spaceTitle: "Écran dans l'espace",
    spaceLine: "Reste en place quand vous tournez la tête.",
    steadyTitle: "Steady",
    steadyLine: "Les lunettes tiennent l'écran en place quand vous bougez.",
    offTitle: "Désactivé",
    offLine: "L'image telle quelle, qui suit votre tête.",
    view: "Vue",
    screen: "Écran",
    size: "Taille",
    recentre: "Recentrer",
    buttons: "Sans ce menu : maintenez L4 pour recentrer, R4 pour changer de vue.",
    sendLogs: "Envoyer les journaux à Mike",
    logsLine:
      "Enregistre dans Téléchargements un zip des journaux de Pocket XR, sans e-mails, compte, noms Wi-Fi et Bluetooth ni adresses IP.",
    logsReady: "Préparation des journaux…",
    logsSaved:
      "{name} est enregistré dans Téléchargements. Envoyez-le à connect@mikehaye.com depuis le mode Bureau, ou joignez-le à une issue sur GitHub.",
    logsFailed: "Impossible de créer les journaux : {error}",
  },
  de: {
    looking: "Suche Pocket XR...",
    notRunning: "Pocket XR läuft nicht. Installiere oder aktualisiere es im Desktop-Modus.",
    plugIn: "Steck deine Brille in den USB-C-Anschluss des Deck.",
    noTracking: "{glasses}: Diese Brille hat kein Head-Tracking, das Bild wird so gezeigt, wie es ist.",
    trackingOn: "{glasses} · Head-Tracking an",
    spaceTitle: "Bildschirm im Raum",
    spaceLine: "Bleibt stehen, wenn du den Kopf drehst.",
    steadyTitle: "Steady",
    steadyLine: "Die Brille hält den Bildschirm fest, während du dich bewegst.",
    offTitle: "Aus",
    offLine: "Das Bild, wie es ist, bewegt sich mit dem Kopf.",
    view: "Ansicht",
    screen: "Bildschirm",
    size: "Größe",
    recentre: "Zentrieren",
    buttons: "Ohne dieses Menü: L4 halten zum Zentrieren, R4 halten zum Wechseln der Ansicht.",
    sendLogs: "Logs an Mike senden",
    logsLine:
      "Speichert ein Zip mit den Logs von Pocket XR in Downloads, ohne E-Mail-Adressen, Konto, WLAN- und Bluetooth-Namen und IP-Adressen.",
    logsReady: "Logs werden vorbereitet...",
    logsSaved:
      "{name} liegt in Downloads. Schick es im Desktop-Modus an connect@mikehaye.com oder häng es an ein Issue auf GitHub an.",
    logsFailed: "Logs konnten nicht erstellt werden: {error}",
  },
  it: {
    looking: "Cerco Pocket XR...",
    notRunning: "Pocket XR non è in esecuzione. Installalo o aggiornalo dalla modalità Desktop.",
    plugIn: "Collega gli occhiali alla porta USB-C del Deck.",
    noTracking: "{glasses}: questi occhiali non hanno il tracciamento della testa, quindi l'immagine resta com'è.",
    trackingOn: "{glasses} · tracciamento della testa attivo",
    spaceTitle: "Schermo nello spazio",
    spaceLine: "Resta fermo quando giri la testa.",
    steadyTitle: "Steady",
    steadyLine: "Gli occhiali tengono fermo lo schermo mentre ti muovi.",
    offTitle: "Disattivato",
    offLine: "L'immagine com'è, che segue la testa.",
    view: "Vista",
    screen: "Schermo",
    size: "Dimensione",
    recentre: "Ricentra",
    buttons: "Senza questo menu: tieni premuto L4 per ricentrare, R4 per cambiare vista.",
    sendLogs: "Invia i log a Mike",
    logsLine: "Salva in Download un zip con i log di Pocket XR, senza email, account, nomi Wi-Fi e Bluetooth e indirizzi IP.",
    logsReady: "Preparo i log...",
    logsSaved:
      "{name} è stato salvato in Download. Invialo a connect@mikehaye.com dalla modalità Desktop o allegalo a una issue su GitHub.",
    logsFailed: "Impossibile creare i log: {error}",
  },
  ru: {
    looking: "Ищем Pocket XR...",
    notRunning: "Pocket XR не запущен. Установите или обновите его в режиме рабочего стола.",
    plugIn: "Подключите очки к порту USB-C на Deck.",
    noTracking: "{glasses}: у этих очков нет отслеживания головы, поэтому картинка показывается как есть.",
    trackingOn: "{glasses} · отслеживание головы включено",
    spaceTitle: "Экран в пространстве",
    spaceLine: "Остаётся на месте, когда вы поворачиваете голову.",
    steadyTitle: "Steady",
    steadyLine: "Очки удерживают экран на месте, пока вы двигаетесь.",
    offTitle: "Выкл.",
    offLine: "Картинка как есть, двигается вместе с головой.",
    view: "Вид",
    screen: "Экран",
    size: "Размер",
    recentre: "По центру",
    buttons: "Без этого меню: удерживайте L4, чтобы вернуть по центру, R4, чтобы сменить вид.",
    sendLogs: "Отправить логи Майку",
    logsLine:
      "Сохраняет в «Загрузки» один zip с логами Pocket XR без адресов почты, учётной записи, имён Wi-Fi и Bluetooth и IP-адресов.",
    logsReady: "Готовим логи...",
    logsSaved:
      "{name} сохранён в «Загрузки». Отправьте его на connect@mikehaye.com из режима рабочего стола или приложите к issue на GitHub.",
    logsFailed: "Не удалось собрать логи: {error}",
  },
};

export function fill(s: string, values: Record<string, string>): string {
  return s.replace(/\{(\w+)\}/g, (m, k: string) => (k in values ? values[k] : m));
}

// The language before the service has answered: the last one it gave, else the browser's (Steam's UI language).
let lastLang: string | null = null;

export function wordsFor(code?: string | null): Words {
  if (code) lastLang = code;
  const nav = typeof navigator !== "undefined" ? navigator.language : "";
  const c = (code || lastLang || nav || "en").replace("-", "_");
  if (WORDS[c]) return WORDS[c];
  const base = c.split("_")[0].toLowerCase();
  if (base === "zh") return WORDS[/_(TW|HK|MO|Hant)/i.test(c) ? "zh_TW" : "zh_CN"];
  if (base === "pt") return WORDS.pt_BR;
  return WORDS[base] || WORDS.en;
}
