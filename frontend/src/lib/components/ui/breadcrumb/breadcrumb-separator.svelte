<script lang="ts">
	import type { HTMLAttributes } from "svelte/elements";
	import { ChevronRight } from "lucide-svelte";
	import { cn } from "$lib/utils";

	let { class: className, children, ...rest }: HTMLAttributes<HTMLLIElement> = $props();
</script>

<li
	role="presentation"
	aria-hidden="true"
	class={cn("[&>svg]:size-3.5", className)}
	{...rest}
>
	{#if children}
		{@render children()}
	{:else}
		<ChevronRight />
	{/if}
</li>
