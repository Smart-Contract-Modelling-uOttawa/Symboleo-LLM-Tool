import { ChevronDown } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Separator } from '@/components/ui/separator'
import type { OptionsResponse } from '@/api/types'
import { FEW_SHOT, type StageFormValues } from './stageForm'

interface StageSectionProps {
  title: string
  id: string
  open: boolean
  onOpenChange: (open: boolean) => void
  state: StageFormValues
  options: OptionsResponse
  onChange: (updater: (prev: StageFormValues) => StageFormValues) => void
}

export function StageSection({
  title,
  id: titleId,
  open,
  onOpenChange,
  state,
  options,
  onChange,
}: StageSectionProps) {
  const hasFewShotExamples = options.examples.length > 0

  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <div className="border rounded-lg">
        <CollapsibleTrigger className="flex items-center justify-between w-full px-4 py-3 text-sm font-medium">
          {title}
          <ChevronDown
            size={16}
            className={`transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Separator />
          <div className="p-4 space-y-4">

            {/* Model */}
            <div className="space-y-1.5">
              <Label>Model</Label>
              <Select
                value={state.model}
                onValueChange={v => onChange(prev => ({ ...prev, model: v }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select model" />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(options.models).map(([provider, models]) => (
                    <SelectGroup key={provider}>
                      <SelectLabel className="capitalize">{provider}</SelectLabel>
                      {models.map(m => (
                        <SelectItem key={m} value={m}>{m}</SelectItem>
                      ))}
                    </SelectGroup>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Strategy */}
            <div className="space-y-1.5">
              <Label>Strategy</Label>
              <Select
                value={state.strategy}
                onValueChange={v => onChange(prev => ({ ...prev, strategy: v, example_files: [] }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select strategy" />
                </SelectTrigger>
                <SelectContent>
                  {options.strategies.map(s => (
                    <SelectItem
                      key={s}
                      value={s}
                      disabled={s === FEW_SHOT && !hasFewShotExamples}
                    >
                      {s}
                      {s === FEW_SHOT && !hasFewShotExamples ? ' (no examples available)' : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Example files — shown only for few_shot */}
            {state.strategy === FEW_SHOT && (
              <div className="space-y-2">
                <Label>Example Files</Label>
                <div className="space-y-1.5 pl-1">
                  {options.examples.map(ex => (
                    <div key={ex} className="flex items-center gap-2">
                      <Checkbox
                        id={`${titleId}-ex-${ex}`}
                        checked={state.example_files.includes(ex)}
                        onCheckedChange={checked => {
                          onChange(prev => ({
                            ...prev,
                            example_files: checked
                              ? [...prev.example_files, ex]
                              : prev.example_files.filter(f => f !== ex),
                          }))
                        }}
                      />
                      <Label
                        htmlFor={`${titleId}-ex-${ex}`}
                        className="font-normal cursor-pointer"
                      >
                        {ex}
                      </Label>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Temperature */}
            <div className="space-y-1.5">
              <Label htmlFor={`${titleId}-temp`}>Temperature</Label>
              <Input
                id={`${titleId}-temp`}
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={state.temperature}
                onChange={e => onChange(prev => ({ ...prev, temperature: e.target.value }))}
              />
            </div>

            {/* Include grammar */}
            <div className="flex items-center gap-2">
              <Checkbox
                id={`${titleId}-grammar`}
                checked={state.include_grammar}
                onCheckedChange={v =>
                  onChange(prev => ({ ...prev, include_grammar: !!v }))
                }
              />
              <Label
                htmlFor={`${titleId}-grammar`}
                className="font-normal cursor-pointer"
              >
                Include grammar
              </Label>
            </div>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}
