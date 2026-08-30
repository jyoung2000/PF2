import { useState } from 'react'
import { BaserowCard, DiscordCard } from '../components/IntegrationCards'
import { KnowledgeCard } from '../components/KnowledgeCard'
import { ProvidersCard } from '../components/ProvidersCard'
import { CompanionCard } from '../components/CompanionCard'
import { GrokCard, XSourceCard } from '../components/XGrokCard'
import { api } from '../api'
import { Field, NumberSetting, Section, TextSetting, ToggleSetting } from '../components/SettingsKit'
import { ConfirmModal, Spinner } from '../components/Primitives'
import { formatBytes } from '../lib/format'
import { useFetch } from '../lib/hooks'
import { useSettings } from '../lib/settings'
import { toastError, toastSuccess } from '../lib/toast'

interface StorageStats {
  post_count: number
  image_count: number
  video_count: number
  media_files: number
  disk_used_bytes: number
  db_bytes: number
  original_bytes: number
  stored_bytes: number
  saved_bytes: number
  data_dir: string
}

function StorageSection() {
  const { data, reload } = useFetch(() => api.get<StorageStats>('/api/settings/storage'))
  const [purging, setPurging] = useState(false)
  const [confirm, setConfirm] = useState<number | null>(null)
  const [days, setDays] = useState(90)

  const preview = async () => {
    try {
      const r = await api.post<{ would_delete: number }>('/api/settings/purge', {
        older_than_days: days,
        dry_run: true,
      })
      setConfirm(r.would_delete)
    } catch (e) {
      toastError((e as Error).message)
    }
  }

  const purge = async () => {
    setPurging(true)
    try {
      const r = await api.post<{ deleted: number; freed_bytes: number }>('/api/settings/purge', {
        older_than_days: days,
        dry_run: false,
      })
      toastSuccess(`Purged ${r.deleted} posts, freed ${formatBytes(r.freed_bytes)}`)
      reload()
    } catch (e) {
      toastError((e as Error).message)
    } finally {
      setPurging(false)
    }
  }

  return (
    <Section
      title="Storage"
      hint="Media is lossy-compressed on ingest; favorites are never purged."
      id="storage"
    >
      {data ? (
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[13px]">
          <div className="card !bg-well p-3">
            <dt className="text-faint text-[11.5px]">Posts</dt>
            <dd className="font-display text-[18px] tabular-nums">{data.post_count}</dd>
            <dd className="text-faint text-[11.5px] tabular-nums">
              {data.image_count} img · {data.video_count} vid
            </dd>
          </div>
          <div className="card !bg-well p-3">
            <dt className="text-faint text-[11.5px]">Disk used</dt>
            <dd className="font-display text-[18px] tabular-nums">{formatBytes(data.disk_used_bytes)}</dd>
            <dd className="text-faint text-[11.5px]">db {formatBytes(data.db_bytes)}</dd>
          </div>
          <div className="card !bg-well p-3">
            <dt className="text-faint text-[11.5px]">Saved by compression</dt>
            <dd className="font-display text-[18px] tabular-nums text-emerald-300">
              {formatBytes(data.saved_bytes)}
            </dd>
            <dd className="text-faint text-[11.5px]">
              {formatBytes(data.original_bytes)} → {formatBytes(data.stored_bytes)}
            </dd>
          </div>
          <div className="card !bg-well p-3">
            <dt className="text-faint text-[11.5px]">Data dir</dt>
            <dd className="text-[12px] font-mono break-all">{data.data_dir}</dd>
          </div>
        </dl>
      ) : (
        <Spinner />
      )}
      <div className="flex items-center gap-2 flex-wrap pt-1">
        <span className="text-[13px] text-mute">Purge non-favorite posts older than</span>
        <input
          type="number"
          min={1}
          aria-label="Purge age in days"
          className="input !w-20 tabular-nums"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        />
        <span className="text-[13px] text-mute">days</span>
        <button className="btn-danger" onClick={preview} disabled={purging}>
          {purging ? <Spinner /> : 'Preview purge…'}
        </button>
      </div>
      {confirm !== null && (
        <ConfirmModal
          title="Purge old posts?"
          message={`${confirm} posts older than ${days} days (favorites excluded) will be deleted along with their media files.`}
          confirmLabel={`Purge ${confirm} posts`}
          onConfirm={purge}
          onClose={() => setConfirm(null)}
        />
      )}
    </Section>
  )
}

export function SettingsPage() {
  const { settings, loading, save } = useSettings()

  if (loading || !settings) {
    return (
      <div className="flex justify-center py-20">
        <Spinner className="w-6 h-6" />
      </div>
    )
  }

  return (
    <div className="max-w-3xl space-y-4 fade-in pb-10">
      <div>
        <h1 className="font-display font-medium text-[19px]">Settings</h1>
        <p className="text-[12.5px] text-faint">
          Everything saves to the app database and applies immediately — no restart. `.env` values act as
          defaults.
        </p>
      </div>

      <IntegrationsSections settings={settings} save={save} />

      <Section title="Scrapers" hint="Keys and inputs for the content sources." id="scrapers">
        <Field
          label="Civitai API key (optional)"
          htmlFor="setting-civitai_api_key"
          hint={
            <>
              Higher rate limits + NSFW access. Create one under{' '}
              <a
                className="underline underline-offset-2 hover:text-fg"
                href="https://civitai.com/user/account"
                target="_blank"
                rel="noreferrer"
              >
                civitai.com → Account settings → API keys
              </a>
              .
            </>
          }
        >
          <TextSetting settings={settings} k="civitai_api_key" save={save} secret placeholder="Paste API key" />
        </Field>
        <ToggleSetting
          settings={settings}
          k="civitai_keep_metaless"
          save={save}
          label="Keep Civitai posts that have no prompt metadata (media-only)"
        />
        <Field
          label="Lexica search terms"
          htmlFor="setting-lexica_search_terms"
          hint="Comma-separated; the adapter rotates through them, one per run."
        >
          <TextSetting
            settings={settings}
            k="lexica_search_terms"
            save={save}
            placeholder="cinematic portrait, isometric city, studio lighting"
          />
        </Field>
      </Section>

      <Section title="Library" hint="Browsing defaults and media compression." id="library">
        <ToggleSetting settings={settings} k="nsfw_default_show" save={save} label="Show NSFW posts by default" />
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Image quality (WebP)" htmlFor="setting-image_quality" hint="1–100, default 82">
            <NumberSetting settings={settings} k="image_quality" save={save} min={30} max={100} />
          </Field>
          <Field label="Image max dimension" htmlFor="setting-image_max_dim" hint="Longest side in px">
            <NumberSetting settings={settings} k="image_max_dim" save={save} min={512} max={8192} suffix="px" />
          </Field>
          <Field label="Video CRF" htmlFor="setting-video_crf" hint="Lower = larger + sharper, default 27">
            <NumberSetting settings={settings} k="video_crf" save={save} min={16} max={40} />
          </Field>
          <Field label="Video max height" htmlFor="setting-video_max_height">
            <NumberSetting settings={settings} k="video_max_height" save={save} min={360} max={2160} suffix="px" />
          </Field>
        </div>
        <ToggleSetting
          settings={settings}
          k="keep_originals"
          save={save}
          label="Keep original files alongside compressed copies (uses much more disk)"
        />
      </Section>

      <StorageSection />
    </div>
  )
}

interface IntegrationStatuses {
  baserow: { status: string; last_tested?: string }
  discord: { status: string; last_tested?: string; gateway?: boolean }
}

function IntegrationsSections({
  settings,
  save,
}: {
  settings: Record<string, unknown>
  save: (v: Record<string, unknown>) => Promise<boolean>
}) {
  const { data, reload } = useFetch(() => api.get<IntegrationStatuses>('/api/integrations/status'))
  return (
    <>
      <KnowledgeCard settings={settings} save={save} />
      <ProvidersCard settings={settings} save={save} />
      <CompanionCard settings={settings} save={save} />
      <XSourceCard settings={settings} save={save} />
      <GrokCard settings={settings} save={save} />
      <BaserowCard settings={settings} save={save} status={data?.baserow} reloadStatus={reload} />
      <DiscordCard settings={settings} save={save} status={data?.discord} reloadStatus={reload} />
    </>
  )
}
