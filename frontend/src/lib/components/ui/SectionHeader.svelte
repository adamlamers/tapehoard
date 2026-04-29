<script lang="ts">
    import { type Component } from 'svelte';
    import { cn } from '$lib/utils';

    interface Props {
        title: string;
        icon?: any;
        iconColor?: string;
        class?: string;
    }

    let { title, icon: Icon, iconColor = "text-blue-500", class: className }: Props = $props();
</script>

<div class={cn("flex items-center gap-3 px-2", className)}>
    {#if Icon}
        <div class={cn("p-1.5 rounded-md", iconColor.replace('text-', 'bg-').replace('color', 'color/10').replace('500', '500/10'), iconColor)}>
            <Icon size={16} />
        </div>
    {/if}
    <h2 class="text-sm font-semibold text-text-primary">{title}</h2>
    <div class="h-px flex-1 bg-gradient-to-r from-border-color/60 to-transparent"></div>
</div>
