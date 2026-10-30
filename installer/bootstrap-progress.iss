{ Feedback is advisory. Only the supervisor's exit and outcome determine
  success. Invalid, unavailable, or interrupted reads keep the last message. }
function ReadBootstrapProgress(const Path: String; var Step: Integer;
  var Message: String): Boolean;
var
  Data: TArrayOfString;
  Text, Candidate: String;
begin
  Result := False;
  if not LoadStringsFromFile(Path, Data) then Exit;
  if GetArrayLength(Data) <> 1 then Exit;
  Text := Data[0];
  if (Length(Text) < 3) or (Length(Text) > 256) then Exit;
  if (Text[1] < '0') or (Text[1] > '6') or (Text[2] <> '|') then Exit;
  if (Pos(#13, Text) <> 0) or (Pos(#10, Text) <> 0) or (Pos(#0, Text) <> 0) then Exit;
  Candidate := Text;
  { Strip the prefix in place so non-ASCII activity text stays Unicode. }
  Delete(Candidate, 1, 2);
  Candidate := Trim(Candidate);
  if (Candidate = '') or (Pos('|', Candidate) <> 0) then Exit;
  Step := StrToInt(Copy(Text, 1, 1));
  Message := Candidate;
  Result := True;
end;

function BootstrapProgressCaption(Step: Integer; const Message: String): String;
begin
  if Step > 0 then
    Result := 'Step ' + IntToStr(Step) + ' of 6: ' + Message
  else
    Result := Message;
end;

function BootstrapElapsedCaption(Seconds: Integer): String;
begin
  Result := Format('Elapsed: %d:%.2d. Please keep setup open.', [
    Seconds div 60, Seconds mod 60]);
end;
