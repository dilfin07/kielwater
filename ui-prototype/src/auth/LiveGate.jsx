import { useEffect, useState } from 'react'
import { Center, Paper, Title, Text, PasswordInput, Button, Stack, Badge, Group } from '@mantine/core'
import { BrandMark } from '../components/BrandMark'
import { MODE } from '../api/client'
import { authStatus, login, setToken, getToken } from '../api/liveClient'

// Гейт авторизации для live-режима: если на бэкенде включён пароль и токена нет —
// просим войти (как боевой web). В mock-режиме гейт прозрачный.
function LoginCard({ onOk }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true); setErr('')
    try {
      const r = await login(pw)
      if (r.token) { setToken(r.token); onOk() }
      else setErr(r.error || 'не удалось войти')
    } catch { setErr('бэкенд недоступен') }
    setBusy(false)
  }
  return (
    <Center h="100vh">
      <Paper withBorder p="xl" w={360} radius="md">
        <Group gap={9} wrap="nowrap" mb={4}>
          <BrandMark size={19} />
          <Title order={4} style={{ letterSpacing: '-0.02em' }}>Kielwater</Title>
        </Group>
        <Badge size="xs" variant="light" color="orange" mb="md">live · боевой Pi</Badge>
        <Stack gap="sm">
          <PasswordInput label="Пароль" value={pw} autoFocus
            onChange={(e) => setPw(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()} />
          {err && <Text c="red" size="sm">{err}</Text>}
          <Button onClick={submit} loading={busy} disabled={!pw}>Войти</Button>
        </Stack>
      </Paper>
    </Center>
  )
}

export default function LiveGate({ children }) {
  const [authed, setAuthed] = useState(MODE !== 'live')
  const [needAuth, setNeedAuth] = useState(false)

  useEffect(() => {
    if (MODE !== 'live') return
    authStatus()
      .then((s) => {
        if (!s.auth_enabled) setAuthed(true)
        else if (getToken()) setAuthed(true)
        else setNeedAuth(true)
      })
      .catch(() => setAuthed(true)) // бэк недоступен — не блокируем, вьюхи покажут пустоту
    const onUnauth = () => { setAuthed(false); setNeedAuth(true) }
    window.addEventListener('hlc-unauth', onUnauth)
    return () => window.removeEventListener('hlc-unauth', onUnauth)
  }, [])

  if (authed) return children
  if (needAuth) return <LoginCard onOk={() => { setNeedAuth(false); setAuthed(true) }} />
  return null
}
