<script lang="ts">
    import { cn } from '$lib/utils';
    import { Card } from './card';

    interface Props {
        label: string;
        value: string | number;
        subLabel?: string;
        variant?: 'default' | 'success' | 'error' | 'warning' | 'info';
        class?: string;
        valueClass?: string;
    }

    let { label, value, subLabel, variant = 'default', class: className, valueClass }: Props = $props();

    const valueColors = {
        default: 'text-text-primary',
        success: 'text-success-color',
        error: 'text-error-color',
        warning: 'text-orange-400',
        info: 'text-blue-500'
    };
</script>

<Card class={cn("p-5 flex flex-col gap-1.5", className)}>
    <span class="text-xs font-medium text-text-secondary opacity-60 block">
        {label}
    </span>
    <h4 class={cn("text-2xl font-bold tabular-nums mono", valueColors[variant], valueClass)}>
        {value}
    </h4>
    {#if subLabel}
        <p class="text-[10px] font-medium text-text-secondary uppercase opacity-40 tracking-tight">
            {subLabel}
        </p>
    {/if}
</Card>
