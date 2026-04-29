<script lang="ts">
    import { cn } from '$lib/utils';
    import type { Snippet } from 'svelte';

    interface Props {
        variant?: 'success' | 'error' | 'warning' | 'info' | 'neutral' | 'blue';
        children: Snippet;
        class?: string;
    }

    let { variant = 'neutral', children, class: className }: Props = $props();

    const variants = {
        success: 'text-success-color bg-success-color/10 border-success-color/20',
        error: 'text-error-color bg-error-color/10 border-error-color/20',
        warning: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
        info: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
        blue: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
        neutral: 'text-text-secondary bg-bg-primary border-border-color'
    };
</script>

<span class={cn(
    "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-medium uppercase tracking-wider",
    variants[variant],
    className
)}>
    {@render children()}
</span>
