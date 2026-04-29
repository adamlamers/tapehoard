<script lang="ts">
    import { cn } from '$lib/utils';
    import type { Snippet } from 'svelte';

    interface Props {
        icon?: any;
        title: string;
        description?: string;
        action?: Snippet;
        class?: string;
    }

    let { icon: Icon, title, description, action, class: className }: Props = $props();
</script>

<div class={cn("flex w-full flex-col items-center justify-center p-12 text-center animate-in fade-in zoom-in duration-500", className)}>
    <div class="flex w-full flex-col items-center">
        {#if Icon}
            <div class="w-20 h-20 bg-bg-tertiary rounded-full flex items-center justify-center mb-6 border-2 border-dashed border-border-color opacity-50">
                <Icon size={40} class="text-text-secondary" strokeWidth={1} />
            </div>
        {/if}
        <h2 class="text-lg font-bold text-text-primary">{title}</h2>
        {#if description}
            <p class="text-sm mt-3 text-text-secondary leading-relaxed opacity-60">
                {description}
            </p>
        {/if}
        {#if action}
            <div class="mt-8">
                {@render action()}
            </div>
        {/if}
    </div>
</div>
