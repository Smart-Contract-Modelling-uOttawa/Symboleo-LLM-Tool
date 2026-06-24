import { ChevronDown } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import type { AdvancedFormValues } from './stageForm'

interface AdvancedSectionProps {
  // Prefixes element ids so multiple instances (one per experiment) don't collide.
  idPrefix: string
  value: AdvancedFormValues
  onChange: (updater: (prev: AdvancedFormValues) => AdvancedFormValues) => void
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function AdvancedSection({
  idPrefix,
  value,
  onChange,
  open,
  onOpenChange,
}: AdvancedSectionProps) {
  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <CollapsibleTrigger className="flex items-center gap-2 w-full text-sm font-medium py-1">
        <ChevronDown
          size={16}
          className={`transition-transform ${open ? 'rotate-180' : ''}`}
        />
        Advanced Options
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-4 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}-num_candidates`}>Candidates</Label>
            <Input
              id={`${idPrefix}-num_candidates`}
              type="number"
              min={1}
              value={value.num_candidates}
              onChange={e => onChange(prev => ({ ...prev, num_candidates: e.target.value }))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}-max_iterations`}>Max Iterations</Label>
            <Input
              id={`${idPrefix}-max_iterations`}
              type="number"
              min={1}
              value={value.max_iterations}
              onChange={e => onChange(prev => ({ ...prev, max_iterations: e.target.value }))}
            />
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Checkbox
              id={`${idPrefix}-stop_on_first`}
              checked={value.stop_on_first_convergence}
              onCheckedChange={v =>
                onChange(prev => ({ ...prev, stop_on_first_convergence: !!v }))
              }
            />
            <Label htmlFor={`${idPrefix}-stop_on_first`} className="font-normal cursor-pointer">
              Stop on first convergence
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id={`${idPrefix}-save_intermediates`}
              checked={value.save_intermediates}
              onCheckedChange={v =>
                onChange(prev => ({ ...prev, save_intermediates: !!v }))
              }
            />
            <Label htmlFor={`${idPrefix}-save_intermediates`} className="font-normal cursor-pointer">
              Save intermediates
            </Label>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
