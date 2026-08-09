import { Box, Group, Stack, Title, Text, List, Table, Code, Anchor, Badge, Paper, ThemeIcon, Divider, ActionIcon, Tooltip, TableOfContents } from '@mantine/core'
import { useMantineColorScheme } from '@mantine/core'
import { Lightning, ArrowLeft, Sun, Moon } from '@phosphor-icons/react'
import { BrandMark } from '../components/BrandMark'
import { CARD, HAIRLINE, SUBTLE_BG } from '../constants'

function Section({ id, title, children }) {
  return (
    <Box component="section" id={id} mb={48}>
      <Title order={2} mb="sm" fw={650} style={{ scrollMarginTop: 72 }}>{title}</Title>
      <Stack gap="sm">{children}</Stack>
    </Box>
  )
}

const P = ({ children }) => <Text size="sm" c="dimmed" lh={1.65}>{children}</Text>
const Term = ({ children }) => <Text span fw={600} c="var(--mantine-color-text)">{children}</Text>

function Callout({ children }) {
  return (
    <Paper withBorder p="sm" radius="md" bg={SUBTLE_BG} style={CARD}>
      <Text size="sm" lh={1.6}>{children}</Text>
    </Paper>
  )
}

function ParamTable() {
  const rows = [
    ['execution_mode', 'Режим ордеров: тейкер (рыночный) или мейкер (пассивная лимитка с фолбэком).', 'taker'],
    ['proportion_include_spot', 'Считать базу как перп-эквити + спот-кэш (истинное плечо к капиталу).', 'true'],
    ['auto_sync', 'Откатывать ли ручные правки к состоянию ведущего. Выкл — правки сохраняются.', 'off'],
    ['favorability_gate', 'Добор/открытие только если цена не хуже входа ведущего. Выходы свободны.', 'on'],
    ['favorability_tol_pct', 'Допуск гейта: насколько хуже входа ведущего ещё можно добирать.', '0.3'],
    ['leverage_cap', 'Потолок суммарного ноционала = эквити × cap.', '3'],
    ['max_notional_per_coin_usd', 'Потолок размера позиции по одной монете, $.', '—'],
    ['leverage_mode', 'mirror — повторять плечо ведущего (с потолком); fixed — всегда заданное.', 'mirror'],
    ['mirror_max_leverage', 'Верхний предел плеча в режиме mirror.', '5'],
    ['data_mode', 'Источник данных: ws (мгновенно) или poll (опрос). Менять на остановке.', 'ws'],
    ['monitor_interval_sec', 'Период опроса монитора (данные интерфейса + backstop-алерты).', '30'],
    ['monitor_instant_notional_usd', 'Порог «мгновенного» алерта; мельче — в сводку.', '—'],
  ]
  return (
    <Paper withBorder radius="md" style={CARD}>
      <Table verticalSpacing="xs" horizontalSpacing="md" striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Параметр</Table.Th>
            <Table.Th>Что делает</Table.Th>
            <Table.Th>Типично</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map(([k, v, d]) => (
            <Table.Tr key={k}>
              <Table.Td><Code>{k}</Code></Table.Td>
              <Table.Td><Text size="sm">{v}</Text></Table.Td>
              <Table.Td><Text size="sm" c="dimmed" ff="monospace">{d}</Text></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Paper>
  )
}

function TopBar() {
  const { colorScheme, toggleColorScheme } = useMantineColorScheme()
  const dark = colorScheme === 'dark'
  return (
    <Box style={{ position: 'sticky', top: 0, zIndex: 10, borderBottom: `1px solid ${HAIRLINE}`, background: 'var(--mantine-color-body)' }}>
      <Group h={52} px="lg" justify="space-between" wrap="nowrap" maw={1180} mx="auto">
        <Group gap={10} wrap="nowrap">
          <BrandMark size={19} />
          <Text fw={700} size="sm" style={{ letterSpacing: '-0.02em' }}>Kielwater</Text>
          <Divider orientation="vertical" />
          <Text size="sm" c="dimmed">Документация</Text>
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Tooltip label={dark ? 'Светлая тема' : 'Тёмная тема'} withArrow>
            <ActionIcon variant="subtle" color="gray" size="lg" onClick={toggleColorScheme}>{dark ? <Sun size={18} /> : <Moon size={18} />}</ActionIcon>
          </Tooltip>
          <Anchor href={import.meta.env.BASE_URL} size="sm"><Group gap={5} wrap="nowrap"><ArrowLeft size={14} />к интерфейсу</Group></Anchor>
        </Group>
      </Group>
    </Box>
  )
}

function SideNav() {
  return (
    <Box w={230} visibleFrom="md" style={{ flexShrink: 0, position: 'sticky', top: 76, alignSelf: 'flex-start' }}>
      <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb="xs" style={{ letterSpacing: 0.5 }}>Разделы</Text>
      <TableOfContents
        variant="light" color="blue" size="sm" radius="sm"
        scrollSpyOptions={{ selector: 'h2' }}
        getControlProps={({ data }) => ({
          onClick: () => data.getNode().scrollIntoView({ behavior: 'smooth', block: 'start' }),
          children: data.value,
        })}
      />
    </Box>
  )
}

export default function DocsPage() {
  return (
    <Box mih="100vh" bg="var(--mantine-color-body)">
      <TopBar />
      <Group align="flex-start" gap={40} wrap="nowrap" maw={1180} mx="auto" px="lg" py="xl">
        <SideNav />
        <Box style={{ flex: 1, minWidth: 0 }} maw={780}>
          <Title order={1} fw={700} mb={6}>Kielwater</Title>
          <Text c="dimmed" size="md" mb="xl">Консоль копи-трейдинга: повторяет позиции ведущего трейдера с Hyperliquid на счёте Binance USDT-M.</Text>

          <Section id="overview" title="Обзор">
            <P>Система копирует не отдельные сделки, а <Term>состояние позиции</Term>. Модель реконсиляционная и идемпотентная: на каждом тике она сравнивает «где ведущий сейчас» (нетто-позиции на Hyperliquid) и «где вы сейчас» (позиции на Binance), вычисляет желаемое состояние под ваш капитал и доводит позицию минимальными ордерами.</P>
            <P>Поэтому пропущенное событие, ручная правка или округление <Term>самозалечиваются на следующем тике</Term> — расхождение всегда сводится к цели.</P>
            <Code block>{`Hyperliquid (ведущий)          Расчёт                      Binance (вы)
  нетто-позиции   ──►   желаемое = пропорция     ──►   diff-ордера
                        под ваш эквити → кэпы
       ▲                                                  │
       └──────────  триггер реконсиляции  ◄───────────────┘
           WS-филл · опрос · реконнект`}</Code>
            <P>Интерфейс состоит из вкладок <Term>Журнал</Term> (результаты копирования), <Term>Монитор</Term> (наблюдение и поиск трейдеров), а также <Term>Логи</Term> и <Term>Настройки</Term>.</P>
          </Section>

          <Section id="accounts" title="Счета и ключи">
            <P>Поддерживается несколько счетов; <Term>активен один</Term> — на нём торгует бот, он выбирается в шапке и в настройках. Ключи каждого счёта хранятся в окружении под своим префиксом и в интерфейсе не показываются.</P>
            <List size="sm" spacing={6} c="dimmed">
              <List.Item><Term>Фьючерсы (USDT-M)</Term> — основной торговый счёт.</List.Item>
              <List.Item><Term>Копи-портфель (lead)</Term> — портфель копи-трейдинга биржи.</List.Item>
              <List.Item><Term>Спот</Term> — спотовый счёт.</List.Item>
            </List>
            <Callout>Переключать активный счёт можно <Term>на остановленном боте и при плоской позиции</Term> — чтобы не оставить открытые позиции без управления на прежнем счёте.</Callout>
          </Section>

          <Section id="monitor" title="Монитор">
            <P>Монитор следит за списком адресов на Hyperliquid и шлёт в Telegram действия ведущих: <Code>открыл</Code> · <Code>долил</Code> · <Code>сократил</Code> · <Code>закрыл</Code> · <Code>развернул</Code> · <Code>сменил плечо</Code>. Он же наполняет вкладку «Монитор» данными по позициям, эквити и риску.</P>
            <Table.ScrollContainer minWidth={420}>
              <Table verticalSpacing="xs" withTableBorder={false}>
                <Table.Thead><Table.Tr><Table.Th>Канал</Table.Th><Table.Th>Что даёт</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  <Table.Tr><Table.Td><Term>WebSocket</Term></Table.Td><Table.Td><Text size="sm">Мгновенный алерт в момент сделки ведущего.</Text></Table.Td></Table.Tr>
                  <Table.Tr><Table.Td><Term>Опрос</Term></Table.Td><Table.Td><Text size="sm">Данные интерфейса и backstop-алерт, если WebSocket что-то упустил.</Text></Table.Td></Table.Tr>
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
            <P>Алерты идут мгновенно из WebSocket; опрос дублирует их только при пропуске (дедуп по адресу, монете и действию). Кнопка <Term>«→ В копир»</Term> делает адрес целью копирования, <Term>колокол</Term> включает/выключает алерты по конкретному адресу.</P>
          </Section>

          <Section id="copier" title="Копир: пропорция и риск">
            <P>Размер позиции считается <Term>честной пропорцией</Term> — вы держите ту же долю своего капитала, что ведущий держит от своего:</P>
            <Code block>{`желаемый_ноционал = ноционал_ведущего × (ваш_эквити / эквити_ведущего)`}</Code>
            <P>Так копируется <Term>эффективное плечо</Term> ведущего. База берётся как перп-эквити + спот-кэш — это отражает истинное плечо к капиталу и не «дышит» при перекладывании маржи между перпом и спотом.</P>
            <Callout>Пример: эффективное плечо ведущего 5×, ваш эквити $1 000 → полная пропорция ≈ $5 000 ноционала (тоже 5×). Дальше её ужимают кэпы.</Callout>
            <Text size="sm" fw={600} mt="xs">Кэпы — срабатывает строжайший</Text>
            <List size="sm" spacing={6} c="dimmed">
              <List.Item><Code>max_notional_per_coin_usd</Code> — потолок размера позиции по одной монете.</List.Item>
              <List.Item><Code>leverage_cap</Code> — потолок суммарного ноционала: эквити × cap.</List.Item>
              <List.Item><Code>mirror_max_leverage</Code> / <Code>fixed_leverage</Code> — потолок плеча самого ордера.</List.Item>
            </List>
            <P><Term>favorability-гейт</Term>: добор и открытие проходят, только если цена не хуже входа ведущего (выходы — свободно). Это бережёт среднюю цену входа и не даёт «уехать» от точки входа ведущего.</P>
          </Section>

          <Section id="reconcile" title="Реконсиляция">
            <P>Цикл запускается тремя триггерами: <Term>WS-филл</Term> ведущего (мгновенно, с коротким дебаунсом, чтобы сбатчить серию сделок), периодический <Term>опрос</Term> как страховка и <Term>реконнект</Term> после обрыва связи.</P>
            <P>На каждом тике система считает желаемое состояние и доводит позицию диффом — отсюда устойчивость к пропускам. Опционально на старте <Term>замораживаются уже прибыльные позиции</Term> ведущего (бот не входит в то, что на момент подключения уже в плюсе).</P>
            <Callout><Term>Авто-синхро (выкл по умолчанию):</Term> применяются только новые движения ведущего, ручные правки не откатываются. Разовая полная синхронизация делается кнопкой с предпросмотром — что именно изменится, прежде чем применить.</Callout>
          </Section>

          <Section id="execution" title="Исполнение">
            <Group gap="xs">
              <Badge variant="light" color="blue">Тейкер</Badge>
              <Badge variant="light" color="grape">Мейкер</Badge>
            </Group>
            <P><Term>Тейкер</Term> — рыночный ордер, исполняется мгновенно (платим спред). Режим по умолчанию, безопасный.</P>
            <P><Term>Мейкер</Term> — пассивная post-only лимитка у лучшей цены: ждёт исполнения → переставляет за ценой → при неудаче добивает тейкером. Имеет смысл на <Term>альтах</Term> (жирный спред + фандинг); на BTC/ETH выигрыша почти нет.</P>
            <Callout>Полное закрытие позиции и аварийный выход (PANIC) — <Term>всегда тейкером</Term>: гарантия выхода важнее экономии на спреде.</Callout>
          </Section>

          <Section id="journal" title="Журнал">
            <P>Единица учёта — <Term>сессия</Term> (период копирования одной цели). Состояния: <Term>Активная</Term>, <Term>Тестовая (бумага)</Term>, <Term>Закрыта</Term>.</P>
            <List size="sm" spacing={6} c="dimmed">
              <List.Item>Реализованный результат считается <Term>только по сделкам бота</Term> (бот-атрибуция); ручной оверлей показывается отдельно.</List.Item>
              <List.Item>Фандинг учитывается на уровне счёта.</List.Item>
              <List.Item><Term>Бумажный режим</Term> — симулятор mark-to-market без обращения к бирже, для проверки логики перед боем.</List.Item>
            </List>
            <P>Визуализация: кривая PnL, календарь дневного результата за год, открытые позиции в боевом формате и таблица сделок.</P>
          </Section>

          <Section id="alerts" title="Уведомления">
            <P><Term>Анти-спам.</Term> Крупное и терминальное событие (открытие, закрытие, разворот выше порога) уходит <Term>мгновенно</Term>; мелкий TWAP-набор сворачивается в <Term>одну сводку</Term> (средняя цена, число сделок, окно). Протухшие по TTL алерты не доставляются.</P>
            <P><Term>Очередь Telegram.</Term> Сообщения отправляются с ограничением скорости и ретраем на лимиты биржи мессенджера — алерты не теряются на всплесках активности.</P>
          </Section>

          <Section id="params" title="Справочник параметров">
            <P>Ключевые настройки и типичные значения. Часть из них управляется прямо из интерфейса (Настройки), часть — в конфиге.</P>
            <ParamTable />
          </Section>

          <Section id="access" title="Доступ и безопасность">
            <List size="sm" spacing={6} c="dimmed">
              <List.Item><Term>Пароль на вход</Term> в интерфейс — включать, когда консоль доступна в сети; для локального запуска не обязателен.</List.Item>
              <List.Item>Пароль защищает только интерфейс и API — сетевой канал шифруется отдельно (VPN/TLS).</List.Item>
              <List.Item><Term>Ключи бирж</Term> хранятся в окружении, а не в интерфейсе и не в репозитории.</List.Item>
              <List.Item>Обновление кода <Term>не перезаписывает</Term> боевой конфиг и состояние.</List.Item>
            </List>
          </Section>

          <Divider my="xl" color={HAIRLINE} />
          <Group gap={8} mb="xl">
            <ThemeIcon variant="light" color="gray" size="sm" radius="xl"><Lightning size={12} weight="fill" /></ThemeIcon>
            <Text size="xs" c="dimmed">Kielwater — документация интерфейса. Значения параметров приведены как ориентир.</Text>
          </Group>
        </Box>
      </Group>
    </Box>
  )
}
