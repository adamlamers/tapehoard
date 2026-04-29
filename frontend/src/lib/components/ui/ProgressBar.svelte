<script lang="ts">
    import { cn } from '$lib/utils';

    interface Props {
        value: number; // 0 to 100
        max?: number;
        variant?: 'blue' | 'success' | 'error' | 'warning';
        size?: 'sm' | 'md' | 'lg';
        class?: string;
        showGlow?: boolean;
    }

    let {
        value = 0,
        max = 100,
        variant = 'blue',
        size = 'md',
        class: className,
        showGlow = true
    }: Props = $props();

    const percentage = $derived(Math.min(100, Math.max(0, (value / max) * 100)));

    const heights = {
        sm: 'h-1',
        md: 'h-1.5',
        lg: 'h-2.5'
    };

    const colors = {
        blue: 'bg-blue-500',
        success: 'bg-success-color',
        error: 'bg-error-color',
        warning: 'bg-orange-400'
    };

    const glows = {
        blue: 'shadow-[0_0_8px_rgba(59,130,246,0.4)]',
        success: 'shadow-[0_0_8px_rgba(46,204,113,0.4)]',
        error: 'shadow-[0_0_8px_rgba(231,76,60,0.4)]',
        warning: 'shadow-[0_0_8px_rgba(251,146,60,0.4)]'
    };
</script>

<div class={cn("w-full bg-bg-primary rounded-full border border-border-color/30 overflow-hidden", heights[size], className)}>
    <div
        class={cn(
            "h-full transition-all duration-500 ease-out",
            colors[variant],
            showGlow && percentage > 0 && glows[variant]
        )}
        style="width: {percentage}%"
    ></div>
</div>
