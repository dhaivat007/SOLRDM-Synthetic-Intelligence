package org.solrdm.app;

import android.content.Intent;
import android.app.Activity;
import android.app.Instrumentation;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.webkit.WebView;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.json.JSONTokener;

/** Real Android WebView checks. No live model or file-understanding claims. */
public final class AgentSmokeTest extends InstrumentationTestCase {
    private AgentActivity activity;
    private int sequence;
    private static final String MARKER = "solrdm-agent-process-restart-verified";

    private void launch() throws Exception {
        Intent intent = new Intent(getInstrumentation().getTargetContext(), AgentActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity = (AgentActivity) getInstrumentation().startActivitySync(intent);
        getInstrumentation().waitForIdleSync();
        awaitTrue("document.readyState === 'complete' && !!document.getElementById('new-chat')"
                + " && !!document.getElementById('native-engine-button')");
    }

    private Object evaluate(String expression) throws Exception {
        CountDownLatch ready = new CountDownLatch(1);
        final String[] value = new String[1];
        getInstrumentation().runOnMainSync(() -> {
            WebView web = activity.getAgentWebView();
            assertNotNull(web);
            web.evaluateJavascript(expression, raw -> { value[0] = raw; ready.countDown(); });
        });
        assertTrue("WebView JavaScript did not return", ready.await(10, TimeUnit.SECONDS));
        return new JSONTokener(value[0] == null ? "null" : value[0]).nextValue();
    }

    private void awaitTrue(String expression) throws Exception {
        long deadline = SystemClock.uptimeMillis() + 30000;
        while (SystemClock.uptimeMillis() < deadline) {
            if (Boolean.TRUE.equals(evaluate("Boolean(" + expression + ")"))) return;
            SystemClock.sleep(75);
        }
        fail("WebView condition timed out: " + expression);
    }

    private JSONObject promise(String expression) throws Exception {
        String key = "__androidSmoke" + (++sequence);
        evaluate("window." + key + " = undefined; (async () => { try { window." + key
                + " = JSON.stringify(await (" + expression + ")); } catch (error) { window." + key
                + " = JSON.stringify({testError:String(error)}); } })();");
        awaitTrue("typeof window." + key + " === 'string'");
        JSONObject result = new JSONObject(String.valueOf(evaluate("window." + key)));
        assertFalse("JavaScript operation failed: " + result, result.has("testError"));
        return result;
    }

    public void testAgentToolsAndPersistence() throws Exception {
        launch();
        assertEquals("https://appassets.androidplatform.net", evaluate("location.origin"));
        JSONObject status = promise("fetch('/api/status').then(r => r.json())");
        assertFalse("No model credential is bundled with this APK", status.getBoolean("modelConfigured"));
        JSONObject chat = promise("fetch('/api/chat', {method:'POST',headers:{'Content-Type':'application/json'},"
                + "body:JSON.stringify({text:'hello'})}).then(async r => ({status:r.status,body:await r.json()}))");
        assertEquals(503, chat.getInt("status"));
        assertEquals("MODEL_NOT_CONFIGURED", chat.getJSONObject("body").getString("code"));
        JSONObject calculation = promise("fetch('/api/tools', {method:'POST',headers:{'Content-Type':'application/json'},"
                + "body:JSON.stringify({name:'simulate_projectile',args:{speed:10,angle:45,gravity:10}})})"
                + ".then(r => r.json())");
        assertEquals("completed", calculation.getString("status"));
        assertEquals(10.0, calculation.getJSONObject("data").getDouble("range"), 1e-9);
        assertEquals(200, calculation.getJSONObject("data").getJSONArray("points").length());
        JSONObject invalid = promise("fetch('/api/tools', {method:'POST',headers:{'Content-Type':'application/json'},"
                + "body:JSON.stringify({name:'run_shell',args:{}})}).then(async r => ({status:r.status}))");
        assertTrue("Unknown tools must be rejected", invalid.getInt("status") >= 400);
        evaluate("document.getElementById('new-chat').click(); document.getElementById('starter-simulate').click();"
                + "document.getElementById('tool-speed').value='10';document.getElementById('tool-angle').value='45';"
                + "document.getElementById('tool-gravity').value='10';document.getElementById('tool-form').requestSubmit();");
        awaitTrue("document.getElementById('tool-status').textContent === 'Result recorded.'");
        assertEquals(Boolean.TRUE, evaluate("!!document.querySelector('#tool-result .result-chart')"));
        evaluate("document.getElementById('save-tool-result').click(); localStorage.setItem('solrdm.android.restart',"
                + JSONObject.quote(MARKER) + ");");
        assertEquals(Boolean.TRUE, evaluate("!!document.querySelector('#messages .receipt')"));
        JSONObject saved = new JSONObject(String.valueOf(evaluate("localStorage.getItem('solrdm.conversations.v1')")));
        assertTrue(saved.getJSONArray("conversations").length() > 0);
        assertEquals(MARKER, evaluate("localStorage.getItem('solrdm.android.restart')"));
        // Allow the WebView storage backend to flush before the host process-stop phase.
        SystemClock.sleep(500);
        Instrumentation.ActivityMonitor engineMonitor = getInstrumentation().addMonitor(
                MainActivity.class.getName(), null, false);
        try {
            evaluate("document.getElementById('native-engine-button').click();");
            Activity engine = getInstrumentation().waitForMonitorWithTimeout(engineMonitor, 10000);
            assertNotNull("Native Python engine button must open the retained engine screen", engine);
            getInstrumentation().runOnMainSync(engine::finish);
        } finally { getInstrumentation().removeMonitor(engineMonitor); }
    }

    public void testAgentRestartPreservesHistory() throws Exception {
        launch();
        assertEquals("Agent history marker must survive a process stop",
                MARKER, evaluate("localStorage.getItem('solrdm.android.restart')"));
        awaitTrue("!!document.querySelector('#messages .receipt')");
        assertTrue(String.valueOf(evaluate("document.querySelector('#messages .receipt-summary').textContent"))
                .contains("range 10 m"));
        JSONObject status = promise("fetch('/api/status').then(r => r.json())");
        assertFalse(status.getBoolean("modelConfigured"));
    }

    @Override protected void tearDown() throws Exception {
        if (activity != null) getInstrumentation().runOnMainSync(() -> activity.finish());
        super.tearDown();
    }
}
