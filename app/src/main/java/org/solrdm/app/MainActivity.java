package org.solrdm.app;
import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
public class MainActivity extends Activity {
  @Override public void onCreate(Bundle state) {
    super.onCreate(state);
    if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
    LinearLayout layout = new LinearLayout(this);
    layout.setOrientation(LinearLayout.VERTICAL);
    layout.setPadding(24, 24, 24, 24);
    TextView title = new TextView(this); title.setText("SOLRDM • Observation Prototype"); title.setTextSize(22); layout.addView(title);
    EditText input = new EditText(this); input.setId(R.id.observation_input); input.setHint("Enter observation, e.g. A rotor is part of a motor"); layout.addView(input);
    Button observe = new Button(this); observe.setId(R.id.observe_button); observe.setText("Observe"); layout.addView(observe);
    TextView output = new TextView(this); output.setId(R.id.observation_output); output.setText("Limited observation bridge. No pretrained LLM."); layout.addView(output);
    observe.setOnClickListener(v -> {
      try {
        String result = Python.getInstance().getModule("android_bridge").callAttr("observe", getFilesDir().getAbsolutePath(), input.getText().toString()).toString();
        output.setText(result);
      } catch (Exception e) { output.setText("Error: " + e.getMessage()); }
    });
    setContentView(layout);
  }
}
