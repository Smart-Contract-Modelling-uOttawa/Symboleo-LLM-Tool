import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import type { OptionsResponse } from '@/api/types'
import { AXES, type AxisDef, type AxisKey } from './axisExpand'

interface AxisExpanderProps {
  options: OptionsResponse
  onGenerate: (axis: AxisDef, values: string[]) => void
}

// Bulk-generate experiment cards by enumerating one categorical axis (strategy
// or model) over selected values — everything else held constant and the cells
// auto-named. Sugar over manual Add/Duplicate; produces the same cards.
export function AxisExpander({ options, onGenerate }: AxisExpanderProps) {
  const [axisKey, setAxisKey] = useState<AxisKey>(AXES[0].key)
  const [selected, setSelected] = useState<string[]>([])

  const axis = AXES.find(a => a.key === axisKey) ?? AXES[0]
  const values = axis.values(options)

  function chooseAxis(key: AxisKey) {
    setAxisKey(key)
    setSelected([])
  }

  function toggle(value: string) {
    setSelected(prev =>
      prev.includes(value) ? prev.filter(v => v !== value) : [...prev, value],
    )
  }

  function generate() {
    if (selected.length === 0) return
    onGenerate(axis, selected)
    setSelected([])
  }

  return (
    <div
      role="group"
      aria-label="Generate variants"
      className="border border-dashed rounded-lg p-4 space-y-3"
    >
      <div className="flex items-center justify-between">
        <Label className="text-sm">Generate variants</Label>
        <div className="flex gap-1">
          {AXES.map(a => (
            <Button
              key={a.key}
              type="button"
              size="sm"
              variant={a.key === axisKey ? 'default' : 'outline'}
              onClick={() => chooseAxis(a.key)}
            >
              {a.label}
            </Button>
          ))}
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Vary {axis.label.toLowerCase()} over the selected values; correction and
        advanced options are cloned from the first experiment.
      </p>

      <div className="flex flex-wrap gap-1.5">
        {values.map(v => (
          <Button
            key={v}
            type="button"
            size="sm"
            variant={selected.includes(v) ? 'default' : 'outline'}
            onClick={() => toggle(v)}
          >
            {v}
          </Button>
        ))}
      </div>

      <Button
        type="button"
        variant="secondary"
        size="sm"
        disabled={selected.length === 0}
        onClick={generate}
      >
        {selected.length > 0
          ? `Generate ${selected.length} variant${selected.length === 1 ? '' : 's'}`
          : 'Generate variants'}
      </Button>
    </div>
  )
}
