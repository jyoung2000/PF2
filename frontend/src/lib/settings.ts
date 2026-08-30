import { useCallback } from 'react'
import { api } from '../api'
import { useFetch } from './hooks'
import { toastError, toastSuccess } from './toast'

export type SettingsMap = Record<string, unknown>

export function useSettings() {
  const { data, loading, error, reload, setData } = useFetch(() =>
    api.get<{ settings: SettingsMap; secret_keys: string[] }>('/api/settings'),
  )

  const save = useCallback(
    async (values: SettingsMap, quiet = false) => {
      try {
        const r = await api.put<{ settings: SettingsMap; applied: string[] }>('/api/settings', values)
        setData((prev) => (prev ? { ...prev, settings: r.settings } : prev))
        if (!quiet) toastSuccess('Settings saved — applied immediately')
        return true
      } catch (e) {
        toastError(`Couldn't save: ${(e as Error).message}`)
        return false
      }
    },
    [setData],
  )

  return {
    settings: data?.settings ?? null,
    secretKeys: data?.secret_keys ?? [],
    loading,
    error,
    reload,
    save,
  }
}

/** True when a masked secret has a stored value ("••••1234"). */
export function secretIsSet(value: unknown): boolean {
  return typeof value === 'string' && value.length > 0
}
