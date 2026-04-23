<script lang="ts">
	import type { HTMLAttributes } from "svelte/elements";
	import { cn } from "$lib/utils";

	let { class: className, children, ...rest }: HTMLAttributes<HTMLSpanElement> = $props();
</script>

<span
	role="link"
	aria-disabled="true"
	aria-current="page"
	class={cn("font-normal text-foreground", className)}
	{...rest}
>
	{@render children?.()}
</span>
