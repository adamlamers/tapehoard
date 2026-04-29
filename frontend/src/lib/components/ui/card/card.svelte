<script lang="ts">
	import { cn } from "$lib/utils";
	import type { HTMLAttributes } from "svelte/elements";

	let { class: className, children, ...rest }: HTMLAttributes<HTMLDivElement> = $props();
</script>

<div
	class={cn("rounded-xl border border-border-color bg-bg-secondary text-text-primary shadow-xl", className)}
	{...rest}
>
	{@render children?.()}
</div>
