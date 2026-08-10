import { useState } from 'react'
import { Box, Group, Paper, Text, Badge, Button, ActionIcon, Tooltip, TextInput, Stack, Loader, Modal } from '@mantine/core'
import { Plus, Trash, ArrowSquareOut, ArrowRight, X, Bell, BellSlash, CaretDown } from '@phosphor-icons/react'
import { CARD, SUBTLE_BG, HAIRLINE } from '../constants'
import { useMonitors, useMonitorActions } from '../api/queries'
import { useT } from '../settings/i18n'

function Metric({ label, value, color, w = 120 }) {
  return (
    <Box w={w} style={{ flexShrink: 0 }}>
      <Text fz={10} c="dimmed" lh={1.2}>{label}</Text>
      <Text size="sm" fw={600} c={color} lh={1.3} truncate>{value}</Text>
    </Box>
  )
}

function MarginBar({ pct }) {
  const color = pct < 30 ? 'teal' : pct < 70 ? 'yellow' : 'red'
  return (
    <Box w={130} style={{ flexShrink: 0 }}>
      <Text fz={10} c="dimmed" lh={1.2}>Margin Used Ratio</Text>
      <Group gap={8} wrap="nowrap" mt={2}>
        <Box style={{ flex: 1, height: 5, borderRadius: 3, background: HAIRLINE, overflow: 'hidden' }}>
          <Box style={{ width: `${Math.min(pct, 100)}%`, height: '100%', background: `var(--mantine-color-${color}-5)` }} />
        </Box>
        <Text size="xs" fw={600}>{pct}%</Text>
      </Group>
    </Box>
  )
}

function PositionCard({ p }) {
  const t = useT()
  const pc = p.upnl.startsWith('+') ? 'teal' : 'red'
  return (
    <Paper withBorder p="sm" radius="md" w={300} bg={SUBTLE_BG} style={CARD}>
      <Group gap={8} wrap="nowrap" mb={8}>
        <Text fw={700} size="sm">{p.coin}</Text>
        {p.dex && <Badge size="xs" color="grape" variant="light" title={`builder-dex ${p.dex} · TradFi`}>{p.dex}</Badge>}
        <Text size="xs" c="dimmed">${p.price}</Text>
        <Badge size="xs" color={p.side === 'SHORT' ? 'red' : 'teal'} variant="light">{p.side}</Badge>
        <Text size="xs" c="dimmed">{p.marginType} {p.lev}</Text>
      </Group>
      <Group gap={0} grow wrap="nowrap" align="flex-start">
        <Box><Text fz={10} c="dimmed">{t('mon.volume')}</Text><Text size="xs" fw={600}>{p.notional}</Text></Box>
        <Box><Text fz={10} c="dimmed">uPnL</Text><Text size="xs" fw={600} c={pc}>{p.upnl}</Text><Text fz={10} fw={600} c={pc}>{p.upnlPct}</Text></Box>
        <Box><Text fz={10} c="dimmed">{t('mon.margin')}</Text><Text size="xs" fw={600}>{p.margin}</Text></Box>
      </Group>
    </Paper>
  )
}

function MonitorRow({ m, actions }) {
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const t = useT()
  const doCopy = () => { m.copying ? actions.clearCopy() : actions.setCopy(m.addr); setConfirm(false) }
  return (
    <Paper withBorder p="sm" radius="md" style={CARD}>
      <Group gap="md" wrap="nowrap" align="center" style={{ minWidth: 1280 }}>
        <Box w={180} style={{ flexShrink: 0, minWidth: 0 }}>
          <Group gap={6} wrap="nowrap">
            <Text fw={600} size="sm" truncate>{m.name}</Text>
          </Group>
          <Text fz={11} c="dimmed" ff="monospace" truncate>{m.addr.slice(0, 10)}…</Text>
        </Box>
        <Metric label="Perp Total Value" value={m.perp} />
        <Metric label={t('mon.spot')} value={m.spot} />
        <Metric label={t('mon.bank')} value={m.bank} />
        <Metric label={t('mon.base')} value={m.base} color="blue" />
        <Metric label="uPnL" value={m.upnl} color={m.upnl.startsWith('+') ? 'teal' : 'red'} />
        <Metric label="Free margin" value={m.free} />
        <MarginBar pct={m.mur} />
        <Metric label={t('mon.positions')} value={m.pos} w={62} />
        <Group gap={4} wrap="nowrap" ml="auto" style={{ flexShrink: 0 }}>
          <Button size="compact-xs" variant={m.copying ? 'light' : 'filled'} color={m.copying ? 'orange' : 'blue'}
            leftSection={m.copying ? null : <ArrowRight size={13} />} onClick={() => setConfirm(true)}>
            {m.copying ? t('mon.uncopy') : t('mon.copy')}
          </Button>
          <Tooltip label={m.alerts ? t('mon.alertsOn') : t('mon.alertsOff')} withArrow>
            <ActionIcon variant="subtle" color={m.alerts ? 'blue' : 'gray'} onClick={() => actions.toggleAlerts(m.id)}>{m.alerts ? <Bell size={16} /> : <BellSlash size={16} />}</ActionIcon>
          </Tooltip>
          <Tooltip label="Hyperdash" withArrow><ActionIcon variant="subtle" color="gray" component="a" href={`https://hyperdash.com/address/${m.addr}`} target="_blank" rel="noreferrer"><ArrowSquareOut size={15} /></ActionIcon></Tooltip>
          <Tooltip label={t('mon.removeMon')} withArrow><ActionIcon variant="subtle" color="red" onClick={() => actions.remove(m.id)}><X size={15} /></ActionIcon></Tooltip>
          <ActionIcon variant="subtle" color="gray" onClick={() => setOpen(!open)} style={{ transform: open ? 'rotate(180deg)' : 'none' }}><CaretDown size={15} /></ActionIcon>
        </Group>
      </Group>
      {open && (
        <Box mt="sm" pt="sm" style={{ borderTop: `1px solid ${HAIRLINE}` }}>
          {m.positions.length
            ? <Group gap="sm" wrap="wrap">{m.positions.map((p, i) => <PositionCard key={i} p={p} />)}</Group>
            : <Text size="xs" c="dimmed">{t('mon.flat')}</Text>}
        </Box>
      )}
      <Modal opened={confirm} onClose={() => setConfirm(false)} centered radius="md" size="sm"
        title={m.copying ? t('mon.uncopyTitle') : t('mon.copyTitle')}>
        <Text size="sm" mb="md"><b>{m.name}</b> {m.copying ? t('mon.uncopyBody') : t('mon.copyBody')}</Text>
        <Group justify="flex-end" gap="sm">
          <Button variant="default" size="xs" onClick={() => setConfirm(false)}>{t('common.cancel')}</Button>
          <Button color={m.copying ? 'orange' : 'blue'} size="xs" onClick={doCopy}>
            {m.copying ? t('mon.uncopy') : t('mon.copy')}
          </Button>
        </Group>
      </Modal>
    </Paper>
  )
}

export default function MonitorView() {
  const { data: monitors = [], isLoading: monLoading } = useMonitors()
  const actions = useMonitorActions()
  const t = useT()
  const [addr, setAddr] = useState('')
  const [name, setName] = useState('')
  const onAdd = () => {
    actions.add({ id: addr, name: name || addr.slice(0, 8), addr, perp: '—', spot: '—', base: '—', upnl: '+$0', free: '—', mur: 0, pos: 0, copying: false, alerts: true, positions: [] })
    setAddr(''); setName('')
  }
  return (
    <Box p="lg" maw={1500} mx="auto" style={{ overflowX: 'auto' }}>
      <Paper withBorder p="sm" radius="md" style={CARD}>
        <Group gap="sm" wrap="nowrap" align="flex-end">
          <TextInput size="xs" style={{ flex: 1 }} label={t('mon.addr')} placeholder="0x…" value={addr} onChange={(e) => setAddr(e.currentTarget.value)} />
          <TextInput size="xs" w={220} label={t('mon.label')} placeholder={t('mon.addrPh')} value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <Button size="xs" leftSection={<Plus size={14} />} disabled={!addr} onClick={onAdd}>{t('mon.add')}</Button>
        </Group>
      </Paper>
      <Stack gap="sm" mt="md">
        {monLoading
          ? <Group justify="center" gap="xs" py="xl"><Loader size="sm" /><Text size="sm" c="dimmed">{t('mon.loading')}</Text></Group>
          : monitors.length ? monitors.map((m) => <MonitorRow key={m.id} m={m} actions={actions} />)
            : <Text size="sm" c="dimmed" ta="center" py="xl">{t('mon.empty')}</Text>}
      </Stack>
    </Box>
  )
}
